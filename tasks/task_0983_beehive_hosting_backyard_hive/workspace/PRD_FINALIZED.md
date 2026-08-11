# Beehive Hosting API — Product Requirements Document

## 1. Introduction

Backyard beekeeping is enjoying a renaissance, but most homeowners who want a hive on their property neither keep bees themselves nor understand the regulatory, safety, and seasonal discipline the practice demands. The Beehive Hosting platform closes that gap: homeowners ("hosts") offer yard space, professional beekeepers install and tend the colonies, and the honey harvest is shared between the host, the operating company, and a reserve pool under a formal agreement. The service must reconcile colony health, food-safety law, liability exposure, seasonal biology, and recurring subscription billing — often within a single business event.

This document specifies the REST API that powers the service. It governs the full operating loop: host onboarding and liability waivers, site registration, hosting agreements and their amendment cycle, hive installation and colony splits, field inspections whose verified results derive each hive's health posture, mite treatments and their harvest embargoes, honey harvest recording and per-season allocation of the crop, swarm response, hive removal with cooling-off fees, education courses that unlock plan and capacity bonuses, incident handling that can block a site, and the season rollover that settles everything at once. All operations are evaluated against a server-side logical clock so that seasonal behavior is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting caller, and `X-User-Role`, declaring the caller's role. The recognized roles, spelled exactly as the server expects them, are `Anonymous`, `Host`, `Beekeeper`, `ApiaryManager`, and `PlatformOps`. A request missing either header, or presenting a role outside this set, is rejected with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER`. A request whose role is not on the endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE`. When a caller acting as `Host` attempts a mutating operation on a resource owned by a different host, the request is rejected with `ERR_NOT_RESOURCE_OWNER`; ownership applies to the caller's agreements, sites, subscriptions, invoices, enrollments, removal jobs, and swarm reports.

Role identity is resolved as follows. When `X-User-Role` is `Host`, `X-User-ID` is the `id` of the acting `Host` entity; ownership checks on any resource that references a `Host` compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Beekeeper`, `ApiaryManager`, or `PlatformOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `recorded_by_id` on an `Inspection`, `approved_by_id` on a `Harvest`, `verified_by_id` on a verified inspection, `assigned_beekeeper_id` on a dispatched swarm event, or `reporter_id` on an incident) but never compares it to any entity's `id`. `Anonymous` callers are unauthenticated and may only self-register as a host.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

---

### 2.3. Pagination

List endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. `offset` defaults to 0. Every list response is sorted by `created_at` in ascending order unless explicitly stated otherwise, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — seasons, hosts, sites, agreements, hives, inspections, treatments, harvests, allocations, swarm events, removal jobs, subscriptions, invoices, enrollments, and incidents — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter starting at its initial value on creation and incremented by one on every mutation, including mutations performed as side effects of another resource's transition.

Timestamps are rendered uniformly: every non-null date- or time-valued field the API returns — requester-supplied instants such as `inspected_at` and `collected_on`, system stamps such as `opened_at`, `signed_at`, and `due_at`, and derived fields such as `last_verified_inspection_at` and `withdrawal_end_date` — is an ISO 8601 UTC timestamp with three fractional digits, exactly the `created_at` format, and a field holding a bare calendar date renders at midnight UTC.

### 2.5. The Logical Clock and Lazy Expiry

The platform runs on a server-side logical clock, not wall-clock time. Before any operator sets it, the logical clock reads exactly `2026-05-01T00:00:00Z`, and it never falls back to wall-clock time. `PlatformOps` may advance the clock through an admin-only test-driving capability that accepts a `to_iso8601` instant; every timestamp the server writes from then on — `opened_at`, `signed_at`, `reported_at`, `issued_at`, and so on — is read from this clock.

Two lifecycle transitions are evaluated lazily against the logical clock on any access to the affected resource, and are also swept at season rollover. An agreement whose `term_end_date` is earlier than the current logical date transitions from `ACTIVE` or `AMENDMENT_PENDING` to `EXPIRED`, with any pending amendment discarded. A swarm event more than 72 hours past its `reported_at` transitions from `REPORTED` or `DISPATCHED` to `EXPIRED`; once lazily expired, a swarm event is not actionable and operations on it are rejected with `ERR_SWARM_NOT_ACTIONABLE`.

### 2.6. Season Rollover and the Checkpoint Sweep

Exactly one season is `OPEN` at any time. The genesis season is created only when no season exists at all; attempting to create the genesis season while one already exists `OPEN`, or to roll over a season that is already `CLOSED`, is rejected with `ERR_SEASON_NOT_CLOSABLE`.

Rollover is the system's great settlement event. When `PlatformOps` rolls over the `OPEN` season — supplying the successor's `name` and `frost_date` — the closing season's `closed_at` is stamped from the logical clock, its `status` becomes `CLOSED`, and the successor season is created `OPEN` with `opened_at` stamped. Within the same request the server performs, atomically, the full checkpoint sweep described in §3.6 and §3.9: allocation finalization, overwinter credit realization, agreement and swarm expiry sweeps, invoice aging and issuance, and the subscription and host standing cascades. The response to a rollover is the successor season, not the closed one.

### 2.7. Colony Posture: Authoritative and Provisional Variants

Each hive carries two posture fields that are derived, never set directly. The **authoritative** variant, `posture`, considers only `VERIFIED` inspections and drives every gate in the system: harvest eligibility, the quarantine lifecycle cascade, and split eligibility. The **provisional** variant, `provisional_posture`, additionally considers `SUBMITTED` inspections and is informational only — an unverified bad report moves `provisional_posture` while `posture` stays unchanged, and the provisional value never gates anything. Both variants are recomputed when an inspection is verified, and `posture` is also recomputed lazily on hive reads. The derivation ladder itself, including all thresholds, is specified in §3.4.

### 2.8. Site Capacity and Occupancy

A site's `base_capacity_hives` (at least 1, defaulting to 2 when omitted) is augmented by bonuses to yield `effective_capacity_hives`: one additional hive if the host's non-`CANCELLED` subscription plan is `PREMIUM`, and one further hive if the host holds a `COMPLETED` `ADV-201` enrollment. Occupancy is the count of hives on the site whose `lifecycle_status` is `ACTIVE` or `QUARANTINED`. Adding a new hive — by installation, split, or swarm capture — requires occupancy to be strictly below `effective_capacity_hives`; when occupancy equals capacity the addition is rejected with `ERR_SITE_CAPACITY_EXCEEDED`, so the equality boundary is inclusive-reject. Capacity is recomputed on hive installation, split, and capture, on subscription plan-change application, and on enrollment completion. Colony death and completed removals each free one unit of occupancy.

### 2.9. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only those two. Proposing an agreement amendment requires the request body to carry `expected_agreement_version` holding the client's last observed `version` of the agreement; if the agreement's current `version` has advanced past that value, the proposal is rejected with `ERR_STALE_VERSION` (HTTP 412). Scheduling a subscription plan change likewise requires `expected_subscription_version` matching the subscription's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412). Both operations are legitimate self-superseding flows — a fresh amendment proposal supersedes a pending one, and a fresh change-plan request supersedes a pending plan — so the stale-version check is the sole guard against a writer acting on an out-of-date view. No other endpoint accepts a version field.

### 2.10. Segregation of Duties

The platform separates field recording from verification. The beekeeper who recorded an inspection may submit or resubmit it, but may never verify or return it: verification and return are performed by an `ApiaryManager` whose `X-User-ID` differs from the inspection's `recorded_by_id`, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. The same wall stands between harvest recording and harvest approval: the approving manager's `X-User-ID` must differ from the harvest's `recorded_by_id`, with `ERR_SEGREGATION_OF_DUTIES` on a match.

### 2.11. Numeric Precision and Decimal Arithmetic

All computations use decimal arithmetic; binary floating point is prohibited anywhere money or mass is derived. Honey masses are rounded half-up to 3 decimal places (`net_kg`, per-harvest host shares, `pool_net_kg`, `reserve_kg`, `operator_kg`, `edu_bonus_kg`). Mite loads are rounded half-up to 2 decimal places. Money is integer cents; where a calculation produces a fractional cent (the per-invoice late fee), each line is rounded half-up to a whole cent before lines are summed. Percentages are handled as basis points (`host_share_base_bps` ranges from 0 to 6000, and the host's effective share is capped at 6000 basis points).

### 2.12. Validation Order

Every request passes through a fixed pipeline of checks, evaluated in this order, and the first failure determines the error returned:

1. **Context headers** — `X-User-ID` and `X-User-Role` present and the role declared; otherwise `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (400).
2. **Role authorization** — the role appears in the endpoint's authorized list; otherwise `ERR_FORBIDDEN_ROLE` (403).
3. **Host ownership** — for host-scoped mutations called as `Host`, the target's `host_id` equals `X-User-ID`; otherwise `ERR_NOT_RESOURCE_OWNER` (403).
4. **Existence** — path identifiers are validated left to right, then body foreign keys (`host_id`, `site_id`, `agreement_id`, `hive_id`, `source_hive_id`); a missing resource yields `ERR_NOT_FOUND` (404).
5. **Request shape** — required fields present, enum values valid, ranges honored (`bees_sampled` at least 1, `quiz_score` between 0 and 100, `term_end_date` after `term_start_date`, `end_date` after `start_date`, `gross_kg` strictly above 0, `email` unique across hosts); otherwise `ERR_INVALID_REQUEST` (400).
6. **State admissibility** — the target resource's current state permits the transition, and the OCC `expected_*_version` match is evaluated at this step; failures surface as `ERR_INVALID_STATE`, `ERR_HIVE_NOT_OPERABLE`, `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_INSPECTION_NOT_SUBMITTED`, `ERR_SUBSCRIPTION_NOT_ACTIVE`, `ERR_INVOICE_NOT_PAYABLE`, `ERR_INVOICE_NOT_VOIDABLE`, `ERR_SWARM_NOT_ACTIONABLE`, `ERR_REMOVAL_NOT_ACTIONABLE`, `ERR_ALLOCATION_NOT_DISTRIBUTABLE`, `ERR_SEASON_NOT_CLOSABLE`, `ERR_ENROLLMENT_NOT_COMPLETABLE`, or `ERR_STALE_VERSION` (412).
7. **Safety** — waiver currency where required (agreement signing, hive installation, removal requests, enrollment), segregation of duties, hive not quarantined for harvest or split, no treatment withdrawal window covering `collected_on`; surfaced as `ERR_WAIVER_CURRENT_REQUIRED`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_HIVE_QUARANTINED`, or `ERR_WITHDRAWAL_WINDOW_ACTIVE`.
8. **Business constraints** — site `CLEAR` for installs, splits, and captures; occupancy below capacity; agreement term windows; treatment windows; crew buffers; one non-terminal subscription per host; course prerequisites; surfaced as `ERR_SITE_BLOCKED`, `ERR_SITE_CAPACITY_EXCEEDED`, `ERR_AGREEMENT_WINDOW_OVERLAP`, `ERR_TREATMENT_WINDOW_OVERLAP`, `ERR_CREW_SCHEDULE_CONFLICT`, `ERR_DUPLICATE_SUBSCRIPTION`, or `ERR_COURSE_PREREQUISITE_NOT_MET` (409).
9. **Referential integrity** — no `REPORTED` incident on the site when a removal is approved, no live hives or in-flight removals when an agreement terminates, at most one non-terminal removal job per hive; surfaced as `ERR_SITE_HAS_OPEN_INCIDENTS`, `ERR_AGREEMENT_HAS_LIVE_HIVES`, or `ERR_REMOVAL_NOT_ACTIONABLE` (409).
10. **Temporal gates** — harvest freshness (a `VERIFIED` inspection with `inspected_at` within the closed window from 30 days before `collected_on` through `collected_on`), the 48-hour removal notice, the 72-hour swarm window, and the requirement that swarm captures and hive installs fall within the agreement term; surfaced as `ERR_INSPECTION_STALE`, `ERR_REMOVAL_NOTICE_TOO_SHORT`, `ERR_SWARM_NOT_ACTIONABLE`, or `ERR_AGREEMENT_NOT_ACTIVE`.
11. **Fiscal standing** — host `ACTIVE` where required (agreement creation, hive installation, enrollment), `balance_due_cents` equal to zero for removal requests, agreement termination, subscription cancellation, and host reactivation, and `reputation_score` of at least 50 for agreement creation; surfaced as `ERR_HOST_NOT_ACTIVE`, `ERR_OUTSTANDING_BALANCE`, or `ERR_HOST_REPUTATION_TOO_LOW`.

## 3. Business Logic & Workflows

### 3.1. Host Onboarding, Waivers, Sites, and Incidents

A homeowner joins the platform by self-registering as an `Anonymous` caller with their `full_name` and `email`; the email must be unique across all hosts. The new `Host` record starts in `APPLICANT` status with `reputation_score` at 100, `honey_credit_kg` at 0, and `balance_due_cents` at 0. Nothing operational can happen until the host signs the liability waiver: signing — the host supplies the `waiver_version` of the document they executed — stamps `waiver_signed_at` from the logical clock, stores the `waiver_version`, and moves an `APPLICANT` host to `ACTIVE`.

Waiver currency is a recurring obligation. A waiver is current only while `waiver_signed_at` is set and the present logical time is no later than 365 days after it. Four operations demand a current waiver — agreement signing, hive installation, removal requests, and course enrollment — and reject with `ERR_WAIVER_CURRENT_REQUIRED` when it lapses. A host already past the applicant stage may renew by signing again, which refreshes `waiver_signed_at` and restores `ACTIVE` status, with one important caveat: a renewal does not cure billing-derived standing. When a `LIMITED` or `SUSPENDED` host still carries unpaid invoices, the renewal leaves the standing untouched; only paying down the balance restores `ACTIVE` through the billing cure cascade.

`PlatformOps` may suspend an `ACTIVE` host (moving them to `SUSPENDED`) and later reactivate them, but reactivation requires `balance_due_cents` equal to zero and is otherwise rejected with `ERR_OUTSTANDING_BALANCE`. Standing also moves automatically: when a rollover pushes a host's subscription into `PAST_DUE` or `SUSPENDED`, the host becomes `LIMITED`; when every invoice on the host's subscriptions is `PAID` or `VOID` so `balance_due_cents` returns to zero, a `LIMITED` host returns to `ACTIVE` without further action.

Each host registers one or more yards as sites, providing the `address`, whether a `water_source` lies within 50 feet, the `setback_feet` from the property line (zero or more), and optionally a `base_capacity_hives` (at least 1; two when omitted). When the caller acts as `Host`, the site's `host_id` must equal `X-User-ID`. A new site starts `CLEAR`. Two events block it: reporting a `SEVERE` incident on the site blocks it immediately, and the site also blocks when the count of its `REPORTED` incidents reaches three. While `BLOCKED`, hive installs, splits, and swarm captures on the site are rejected with `ERR_SITE_BLOCKED`. An `ApiaryManager` restores a `BLOCKED` site to `CLEAR` only once no incident on the site remains in `REPORTED` status.

Anyone on scene — a `Host`, `Beekeeper`, or `ApiaryManager` — may report an incident by supplying the `site_id`, a `severity` of `MINOR` or `SEVERE`, the `occurred_at` time, and a free-text `description`. The server stamps the reporter's `X-User-ID` as `reporter_id` and copies `host_id` from the site at report time; the incident opens in `REPORTED` status. Resolution belongs to an `ApiaryManager`, who supplies an `outcome` of `AT_FAULT`, `NO_FAULT`, or `DISMISSED` and may record a `liability_cents` claim amount (default 0). An `AT_FAULT` resolution decrements the host's `reputation_score` — by 15 for a `SEVERE` incident, by 5 for a `MINOR` one, never below zero — while `NO_FAULT` and `DISMISSED` leave reputation untouched; all three stamp `resolved_at` and are terminal. Reputation gates new business: a host whose `reputation_score` has fallen below 50 cannot have new agreements created for them, failing with `ERR_HOST_REPUTATION_TOO_LOW`.

### 3.2. Agreements: Signing, Amendments, and Termination

A hosting agreement binds one host and one site for a fixed term. `PlatformOps` creates the agreement with `host_id`, `site_id`, an inclusive `term_start_date`, an inclusive `term_end_date` that must fall after the start, and `host_share_base_bps` — the host's base share of net honey in basis points, from 0 to 6000. Creation already enforces two gates: the host's `reputation_score` must be at least 50, and the host must be `ACTIVE` (otherwise `ERR_HOST_NOT_ACTIVE`). Furthermore, the new term — treated as a closed interval — must not overlap the closed term interval of any other agreement on the same site in `PENDING_SIGNATURE`, `ACTIVE`, or `AMENDMENT_PENDING`; an overlap is rejected with `ERR_AGREEMENT_WINDOW_OVERLAP`. The agreement is born `PENDING_SIGNATURE`.

Signing belongs to the host named on the agreement (`host_id` equal to `X-User-ID`), and the signature ceremony is heavily gated, evaluated in the pipeline order of §2.12: the host must be `ACTIVE`; the host's waiver must be current; the site must be `CLEAR`; and no other agreement on the same site in `PENDING_SIGNATURE`, `ACTIVE`, or `AMENDMENT_PENDING` may overlap this agreement's term, again as closed intervals. On success the agreement pins `liability_clause_version` to the host's current `waiver_version`, stamps `signed_at`, becomes `ACTIVE`, and its `version` increments by one.

Shares can be renegotiated mid-term through the amendment cycle. `PlatformOps` proposes an amendment by supplying `proposed_host_share_base_bps` and `expected_agreement_version`. Per §2.9 the request is rejected with `ERR_STALE_VERSION` (HTTP 412) when the supplied version does not match the agreement's current `version` — this OCC check is the only guard, because proposing from either `ACTIVE` or `AMENDMENT_PENDING` is legitimate and a new proposal simply supersedes the pending one. A successful proposal moves the agreement to `AMENDMENT_PENDING`, stores the offered value in `pending_host_share_base_bps`, and increments `version`. The host then resolves the offer: accepting copies `pending_host_share_base_bps` into `host_share_base_bps`, nulls the pending field, returns the agreement to `ACTIVE`, and increments `version`; rejecting nulls the pending field with terms unchanged, returns to `ACTIVE`, and increments `version`. Both decisions require the acting host to own the agreement.

Termination — by `PlatformOps` or by the owning host — is allowed from `ACTIVE` or `AMENDMENT_PENDING` but only when three referential conditions hold simultaneously: no hive under the agreement is `ACTIVE` or `QUARANTINED`, no removal job for any hive of the agreement sits in `REQUESTED`, `APPROVED`, or `SCHEDULED`, and the host's `balance_due_cents` is zero. A live hive or in-flight removal yields `ERR_AGREEMENT_HAS_LIVE_HIVES`; an unpaid balance yields `ERR_OUTSTANDING_BALANCE`. Termination discards any pending amendment and increments `version`. Finally, agreements expire of their own accord: when the current logical date passes `term_end_date`, an `ACTIVE` or `AMENDMENT_PENDING` agreement becomes `EXPIRED` on the next access or at the rollover sweep, with any pending amendment discarded.

### 3.3. Placing Hives: Installs, Splits, and Capacity

An `ApiaryManager` installs a hive by supplying `site_id` and `agreement_id`. Installation requires, in pipeline order: the referenced records to exist; the host to be `ACTIVE`; the host's waiver to be current; the current date to fall within the agreement's term, so the agreement must be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE` otherwise); the site to be `CLEAR`; and occupancy on the site to be strictly below `effective_capacity_hives` (§2.8), with a full site failing as `ERR_SITE_CAPACITY_EXCEEDED`. The new hive is stamped with `installed_at` from the logical clock, starts with `lifecycle_status` `ACTIVE`, and — having no verified inspections yet — derives `posture` `STABLE`. Occupancy rises by one.

A strong colony can be divided: splitting a hive creates a child hive on the same site under the same agreement, with the child's `parent_hive_id` set to the split parent's `id`, lifecycle `ACTIVE`, and posture `STABLE`. Splits obey the same site-clear and capacity gates as installs, and additionally require the parent hive itself to be operable — a `DEAD` or `REMOVED` hive accepts no splits, inspections, harvests, or treatments (`ERR_HIVE_NOT_OPERABLE`) — and a `QUARANTINED` hive may not be split or harvested (`ERR_HIVE_QUARANTINED`). The lineage fields are queryable: hive listings accept optional filters on `site_id`, `agreement_id`, `parent_hive_id`, and `source_swarm_event_id`.

When a colony dies — overwinter loss, collapse, or discovery during an inspection — an `ApiaryManager` marks the hive dead, moving it from `ACTIVE` or `QUARANTINED` to `DEAD` and freeing one unit of site occupancy. A hive also leaves inventory when a removal job completes, transitioning to `REMOVED` and likewise freeing occupancy. Both `DEAD` and `REMOVED` are terminal.

### 3.4. Inspections, Posture, and Quarantine

Field truth enters the system through inspections. A `Beekeeper` records an inspection with the `hive_id`, the `inspected_at` timestamp of the physical visit, the `mites_counted` in the wash sample (zero or more), the `bees_sampled` (at least one), a `disease_flag` for foulbrood or other notifiable disease, a `brood_score` from 0 to 10, whether `queen_seen` is true (queen or fresh eggs observed), and `stores_kg` of honey on frame (zero or more). The recorder's `X-User-ID` is stored as `recorded_by_id`, and the server immediately computes and stores `mite_load_per_100`: the mite count divided by the bees sampled, multiplied by 100, rounded half-up to two decimal places using decimal arithmetic. The inspection opens as `DRAFT`.

Review follows a strict loop with segregation of duties (§2.10). Only the recording beekeeper may submit a `DRAFT` inspection, moving it to `SUBMITTED`. An `ApiaryManager` then either verifies or returns it; attempting either on an inspection not in `SUBMITTED` fails with `ERR_INSPECTION_NOT_SUBMITTED`. A return requires a `return_reason`, moves the inspection to `RETURNED`, and the recorder may later resubmit — the `return_reason` is retained for audit. Verification stamps `verified_by_id`, sets the hive's `last_verified_inspection_at` to the inspection's `inspected_at`, recomputes both posture variants, and is terminal; the hive must not be `DEAD` or `REMOVED` at verify time.

Posture derivation works from a candidate set — the hive's inspections ordered by `inspected_at` descending, ties broken by `created_at` descending — filtered per variant (§2.7). The latest inspection in the candidate set decides; with no qualifying inspection the posture is `STABLE`. From that latest inspection the ladder is evaluated top to bottom, first match winning: `disease_flag` true yields `QUARANTINED`; a `mite_load_per_100` of at least 9.00 yields `QUARANTINED`; at least 3.00 yields `TREATMENT_REQUIRED`; at least 2.00 yields `WATCH`; a `brood_score` below 6 or `stores_kg` below 8 yields `WATCH`; a sighted queen with `brood_score` of at least 8 and `mite_load_per_100` below 1.00 yields `THRIVING`; anything else yields `STABLE`.

Verification can move the colony itself. When a newly verified inspection's authoritative posture evaluates to `QUARANTINED`, an `ACTIVE` hive's `lifecycle_status` cascades to `QUARANTINED`, its `posture` is set to `QUARANTINED`, every harvest of that hive still in `RECORDED` status is voided, and the season's allocation for the hive — if one exists — is recomputed on the projected variant excluding the voided harvests. Conversely, when a later verified inspection's authoritative posture is anything but `QUARANTINED`, a `QUARANTINED` hive returns to `ACTIVE` with its posture set to the newly derived value. Quarantine freezes income: harvesting or splitting a quarantined hive is rejected with `ERR_HIVE_QUARANTINED`.

### 3.5. Treatments, the Withdrawal Embargo, and Harvests

Mite treatment is scheduled by an `ApiaryManager` with the `hive_id`, a `product` of `OXALIC_ACID`, `APIVAR`, or `FORMIC_ACID`, and a planned window from `start_date` to `end_date`. The window is half-open — it covers the start date and every day up to but not including the end date — `end_date` must fall after `start_date`, and the new window must not overlap any existing treatment window on the same hive under half-open semantics, else `ERR_TREATMENT_WINDOW_OVERLAP`. On creation the server derives `withdrawal_end_date` as `end_date` plus 14 days, and the treatment starts `SCHEDULED`. A beekeeper starts it when work begins (the hive must be `ACTIVE` or `QUARANTINED`), stamping `started_at` and moving it `IN_PROGRESS`, and later completes it, stamping `completed_at` and reaching the terminal `COMPLETED` state.

Food safety rides on the withdrawal embargo: a harvest may not be recorded if its `collected_on` falls inside the embargo window — from the treatment's `start_date` up to but not including `withdrawal_end_date` — of any `IN_PROGRESS` or `COMPLETED` treatment on the hive; the rejection is `ERR_WITHDRAWAL_WINDOW_ACTIVE`.

A beekeeper records a harvest with the `hive_id`, the `collected_on` date the supers were pulled, the `gross_kg` extracted (strictly above zero, at most three decimal places), and the refractometer `moisture_pct` reading (0 to 100, at most two decimal places); the recorder's `X-User-ID` becomes `recorded_by_id`. Recording requires an operable hive, freshness of field knowledge — some `VERIFIED` inspection of the hive whose `inspected_at` lies in the closed window from 30 days before `collected_on` through `collected_on`, failing which `ERR_INSPECTION_STALE` — a non-quarantined hive, and a `collected_on` clear of every withdrawal embargo. The server computes `net_kg` immediately: moisture strictly above 18.6 percent is penalized while exactly 18.6 is not, the excess percentage points are divided by 100 and multiplied by both `gross_kg` and a penalty factor of 2.0 to give the moisture penalty in kilograms, and `net_kg` is `gross_kg` minus that penalty, rounded half-up to three decimal places in decimal arithmetic. The harvest is born `RECORDED`. Recording a harvest never creates an allocation, but when the allocation for the currently `OPEN` season and this hive already exists in `PROJECTED` status, recording recomputes its projected variant to include the new harvest (§3.6).

Approval belongs to an `ApiaryManager` other than the recorder (segregation of duties, §2.10), requires the hive to be `ACTIVE` or `QUARANTINED`, and requires the season's allocation for the hive to be neither `FINALIZED` nor `DISTRIBUTED` — a late approval attempt against a settled allocation fails with `ERR_ALLOCATION_NOT_DISTRIBUTABLE`. Approval stamps `approved_by_id` and either creates the allocation for the currently `OPEN` season and this hive, or recomputes it on the projected variant including the newly approved harvest (§3.6). A manager may also void a harvest in `RECORDED` or `APPROVED` status — again only while the allocation is not `FINALIZED` or `DISTRIBUTED` — which recomputes the allocation excluding the voided harvest. Once the allocation is distributed, each of its `APPROVED` harvests settles into `SETTLED`, terminal alongside `VOIDED`.

### 3.6. Honey Allocation and Season Settlement

The honey pool is tracked per season and per hive by a `HoneyAllocation`, created the first time a harvest is approved for the currently `OPEN` season — its `season_id` is that season — and living in `PROJECTED` status while the season runs. The projected variant is recomputed on every harvest approval, every harvest void, every quarantine cascade that voids recorded harvests, and every harvest recording once the pair's allocation exists. It reports `projected_pool_net_kg`, the sum of `net_kg` over the pair's harvests in `RECORDED` or `APPROVED` status, and `projected_host_kg`, computed from those same harvests with all share inputs read live — the agreement's current `host_share_base_bps`, the host's current subscription plan, and the host's current enrollment record. Allocations are listed with optional `season_id` and `hive_id` filters.

Share arithmetic works in basis points. The host's effective rate adds three components: the agreement's base share, a tier bonus of 0 basis points on `BASIC`, 250 on `PLUS`, and 500 on `PREMIUM`, and an education bonus of 200 basis points when the host holds a `COMPLETED` `HOST-101` enrollment; the sum is capped at 6000 basis points. The host's kilograms are then computed harvest by harvest with a pinned order — for each included harvest, multiply its `net_kg` by the effective basis points, divide by ten thousand, and round half-up to three decimal places; then sum the rounded per-harvest amounts. Rounding each harvest first and summing second is mandatory.

Finalization happens only at rollover. The closing season's allocations move from `PROJECTED` to `FINALIZED` with `finalized_at` stamped, and the final variant recomputes everything with inputs pinned at the moment of close: only `APPROVED` harvests count, the agreement's base share is taken as of close, the plan is taken as of close (a `pending_plan` scheduled for the next season does not apply to the closing one), and the education bonus requires the `HOST-101` completion's `completed_at` to be no later than the close time. The final variant writes `pool_net_kg` (the sum of `net_kg` over `APPROVED` harvests only), `effective_bps`, and `host_kg`.

The pool is then divided by a waterfall whose evaluation order is pinned, because the pieces depend on one another. First the pool itself is fixed as just described. Second the host share is computed per the final variant above. Third the education bonus mass `edu_bonus_kg` is fixed: when the education bonus applied, the pool multiplied by 200 and divided by ten thousand, rounded half-up to three decimals; otherwise zero. Fourth the reserve percentage is chosen by pool size: six percent of the pool when `pool_net_kg` reaches at least 100.000 kilograms, three percent below that. Fifth `reserve_kg` is the pool multiplied by the chosen percentage, rounded half-up to three decimals, plus the `edu_bonus_kg` top-up. Sixth `operator_kg` takes the remainder — pool minus host share minus reserve — which makes the conservation identity exact: for every finalized allocation, `host_kg` plus `reserve_kg` plus `operator_kg` equals `pool_net_kg`.

Distribution is a deliberate `PlatformOps` act on a `FINALIZED` allocation; attempting it earlier is rejected with `ERR_ALLOCATION_NOT_DISTRIBUTABLE`. Distribution credits the host's `honey_credit_kg` with the allocation's `host_kg`, moves every `APPROVED` harvest of the season-and-hive pair to `SETTLED`, stamps `distributed_at`, and leaves the allocation `DISTRIBUTED`.

### 3.7. Swarm Response

When bees cluster on a host's property, the host reports a swarm on a site they own, supplying the `site_id` and optionally the suspected parent `source_hive_id`. The server records the reporting host's `X-User-ID` as `reported_by_host_id`, stamps `reported_at`, and opens the event in `REPORTED` status. Speed matters: a swarm event expires 72 hours after `reported_at` (§2.5), and both dispatch and capture evaluate that expiry before anything else — acting on an expired event fails with `ERR_SWARM_NOT_ACTIONABLE`.

A beekeeper answers the call by dispatching themselves, moving the event from `REPORTED` to `DISPATCHED` with their `X-User-ID` stored as `assigned_beekeeper_id`. Only the assigned beekeeper may then resolve the event. A capture — available while the event is unexpired — requires the site to be `CLEAR`, an `ACTIVE` agreement covering the site whose term contains the current date (`ERR_AGREEMENT_NOT_ACTIVE` otherwise), and occupancy strictly below `effective_capacity_hives`. On capture the server creates a new hive on the site under that agreement with `source_swarm_event_id` pointing back at the event, lifecycle `ACTIVE`, posture `STABLE`, occupancy rising by one, and the event's `captured_hive_id` set as it becomes `CAPTURED`. If the swarm eludes the crew, the assigned beekeeper marks it lost and the event ends `LOST`. `CAPTURED`, `LOST`, and `EXPIRED` are all terminal.

### 3.8. Removal Jobs and Cancellation Fees

A host may ask for a hive to be taken away by creating a removal job with the `hive_id` and a `reason` of `RELOCATION`, `NUISANCE`, `HEALTH`, or `EXIT`. The request requires a current waiver, a zero `balance_due_cents` (`ERR_OUTSTANDING_BALANCE` otherwise), and at most one non-terminal removal job per hive — a second open job for the same hive fails with `ERR_REMOVAL_NOT_ACTIONABLE`. The server records the requesting host as `requested_by_host_id`, stamps `requested_at`, and opens the job `REQUESTED`.

The decision sits with an `ApiaryManager`, who submits a `decision` of `APPROVE` or `REJECT` with an optional `decision_reason`. Approval is referentially gated: if any incident on the hive's site is still `REPORTED`, the decision is rejected with `ERR_SITE_HAS_OPEN_INCIDENTS`; otherwise the job becomes `APPROVED`. A rejection moves the job to `REJECTED` and fixes its `cancellation_fee_cents` at zero.

Scheduling an approved job requires a `scheduled_start` no earlier than 48 hours after the current logical time — the boundary is inclusive, so exactly 48 hours qualifies; shorter notice fails with `ERR_REMOVAL_NOTICE_TOO_SHORT` — plus a `crew_id`. Crews need turnaround room: each scheduled job occupies a two-hour window starting at its `scheduled_start`, and no other `SCHEDULED` job with the same `crew_id` may sit closer than two hours to that window — a gap of at least two hours between job windows is required, and a gap of exactly two hours is allowed. A tighter assignment fails with `ERR_CREW_SCHEDULE_CONFLICT`. The scheduled job is later completed by a beekeeper, which stamps `completed_at`, moves the job to `COMPLETED`, and transitions the hive to `REMOVED`, freeing one unit of occupancy.

Cancellation — by the owning host or `PlatformOps` — is possible from `REQUESTED`, `APPROVED`, or `SCHEDULED` and is priced by a cooling-off rule: cancelling within 24 hours of `requested_at` is free, with the boundary inclusive so exactly 24 hours is also free; cancelling later sets `cancellation_fee_cents` to 7500. A fee above zero is not charged on the spot; it enters the host's balance through a stand-alone adjustment invoice at the next rollover, where it rides the carried-balance mechanism of §3.9.

### 3.9. Subscriptions, Invoices, Education, and Host Standing

Every hosted relationship runs on a subscription created by `PlatformOps` with the `host_id` and a `plan` of `BASIC`, `PLUS`, or `PREMIUM`. A host may hold only one non-`CANCELLED` subscription; a duplicate attempt fails with `ERR_DUPLICATE_SUBSCRIPTION`. Choosing `PREMIUM` at creation — and likewise when scheduling a change into `PREMIUM` — requires the host to hold a `COMPLETED` `HOST-101` enrollment, else `ERR_COURSE_PREREQUISITE_NOT_MET`. The monthly fee is pinned by plan at the moment of creation and at each plan-change application: 2999 cents for `BASIC`, 4999 for `PLUS`, 7999 for `PREMIUM`, stored as `monthly_fee_cents`. The subscription starts `ACTIVE` with `activated_at` stamped, and creation immediately issues the first invoice with carried balance 0, late fee 0, and overwinter credit 0.

Plan changes are scheduled, not immediate. The owning host calls the change with the desired `plan` and an `expected_subscription_version`; per §2.9 a version mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), and since a fresh change legitimately supersedes a pending one (an `ACTIVE` to `ACTIVE` self-loop), the stale-version check is the only guard. Success stores the choice in `pending_plan` — replacing any prior pending plan — and increments the subscription's `version`. At the next rollover the pending plan is applied, `monthly_fee_cents` is re-pinned, and site capacities are recomputed. Cancelling a subscription requires ownership and a zero `balance_due_cents`, clears `pending_plan`, and is terminal from `ACTIVE`, `PAST_DUE`, or `SUSPENDED`.

Education runs alongside billing. A host enrolls in courses — `HOST-101`, `ADV-201`, or `QUEEN-301` — with their `host_id` and `course_code`; enrollment requires an `ACTIVE` host with a current waiver, and honors prerequisite chains: `ADV-201` requires a `COMPLETED` `HOST-101`, and `QUEEN-301` requires a `COMPLETED` `ADV-201`, with violations rejected as `ERR_COURSE_PREREQUISITE_NOT_MET`. A new enrollment is `ENROLLED`. `PlatformOps` records the quiz outcome by submitting the `quiz_score` (0 to 100): a score of at least 80 completes the course, stamping `completed_at`; below 80 fails it. Both outcomes are terminal, completing an already-terminal enrollment fails with `ERR_ENROLLMENT_NOT_COMPLETABLE`, and retakes simply create a new enrollment row. Completed courses pay dividends elsewhere: `HOST-101` unlocks `PREMIUM` and adds 200 basis points to honey share, while `ADV-201` adds one unit of site capacity (§2.8).

Invoices are issued at subscription creation and at every rollover for subscriptions in `ACTIVE` or `PAST_DUE`. Each invoice carries its `subscription_id`, a `period_label` such as `2026-05`, and a set of computed lines that are each rounded to whole cents before being summed — per-line rounding first, summation second, in pinned order. `fee_cents` is the subscription's pinned `monthly_fee_cents`. `carried_balance_cents` sums the `total_cents` of the subscription's unpaid prior invoices — those `OPEN` or `OVERDUE` — and is zero for the very first invoice. `late_fee_cents` accrues per unpaid prior invoice: for each, count the full weeks overdue as the floor of the elapsed time since its `due_at` divided by seven days, round half-up to a whole cent three percent of that invoice's entire unpaid `total_cents` — prior late fees included, the compounding is intended — and multiply by the weeks overdue; the invoice's late fee is the sum across unpaid priors. `overwinter_credit_cents` is the realized survival credit described below, present only on rollover-issued invoices. The invoice's `total_cents` is fee plus carried plus late minus credit, floored at zero. Each invoice is stamped `issued_at`, with `due_at` exactly seven days later, and opens in `OPEN` status.

The overwinter credit rewards colony survival: 4000 cents for each of the host's hives — across all of the host's sites — whose `installed_at` is on or before the closing season's `frost_date` and whose lifecycle is `ACTIVE` or `QUARANTINED`. It exists in two variants. The projected variant, `projected_overwinter_credit_cents`, is computed live on subscription reads against the currently `OPEN` season's `frost_date` and the hive set as it stands right now — so a hive that dies between the read and the close still counts in the projection. The realized variant is computed at rollover against the closing season and lands as `overwinter_credit_cents` on the rollover-issued invoice.

Rollover is also the billing engine's aging step. For every subscription in `ACTIVE` or `PAST_DUE`, any unpaid invoice whose `due_at` has passed becomes `OVERDUE`; a fresh next-period invoice is issued per the line math above; and standing cascades — a subscription with any `OVERDUE` invoice after aging moves from `ACTIVE` to `PAST_DUE`, and one that entered the rollover already `PAST_DUE` and still has unpaid invoices moves to `SUSPENDED`. Either way the host becomes `LIMITED` (a `SUSPENDED` subscription's host remains `LIMITED`). When payment later leaves no `OPEN` or `OVERDUE` invoice on the subscription, the subscription returns from `PAST_DUE` or `SUSPENDED` to `ACTIVE` and, absent any other blocking condition, the host returns from `LIMITED` to `ACTIVE`.

Payment and voiding close the loop. An `OPEN` or `OVERDUE` invoice can be paid by the owning host or `PlatformOps`, stamping `paid_at` and moving to `PAID`; paying a `PAID` or `VOID` invoice fails with `ERR_INVOICE_NOT_PAYABLE`. `PlatformOps` may instead void an unpaid invoice, moving it from `OPEN` or `OVERDUE` to `VOID` — voiding a `PAID` invoice fails with `ERR_INVOICE_NOT_VOIDABLE` — which excludes it from the host's `balance_due_cents` and re-evaluates the cure cascade. That balance, visible on every host read, is simply the sum of `total_cents` over invoices in `OPEN` or `OVERDUE` across the host's subscriptions. The rollover sweep also handles the remaining scheduled work of §2.5 and §3.2: agreements past their term become `EXPIRED`, stale swarm events become `EXPIRED`, and allocations finalize per §3.6.

## 4. Endpoint Definitions

The API is mounted under `/api`. Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. Readers should reconstruct full request and response semantics from §3; the table below is a navigational index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the server logical clock (default 2026-05-01T00:00:00Z) | PlatformOps |
| POST | `/api/seasons` | Create the genesis season | PlatformOps |
| GET | `/api/seasons/{id}` | Read a season | Host, Beekeeper, ApiaryManager, PlatformOps |
| POST | `/api/seasons/{id}/rollover` | Close the OPEN season, open its successor, run the checkpoint sweep | PlatformOps |
| POST | `/api/hosts` | Register a host (self-service) | Anonymous |
| GET | `/api/hosts/{id}` | Read a host with current computed fields | Host, Beekeeper, ApiaryManager, PlatformOps |
| POST | `/api/hosts/{id}/sign-waiver` | Sign or renew the liability waiver | Host |
| POST | `/api/hosts/{id}/suspend` | Suspend a host | PlatformOps |
| POST | `/api/hosts/{id}/reactivate` | Reactivate a suspended host (zero balance required) | PlatformOps |
| POST | `/api/sites` | Create a site for a host | Host |
| GET | `/api/sites/{id}` | Read a site | Host, Beekeeper, ApiaryManager, PlatformOps |
| GET | `/api/sites` | List sites, optionally filtered by host | Host, Beekeeper, ApiaryManager, PlatformOps |
| POST | `/api/sites/{id}/unblock` | Clear a BLOCKED site after its incidents resolve | ApiaryManager |
| POST | `/api/agreements` | Create a host agreement (PENDING_SIGNATURE) | PlatformOps |
| GET | `/api/agreements/{id}` | Read an agreement (lazy expiry applied) | Host, Beekeeper, ApiaryManager, PlatformOps |
| GET | `/api/agreements` | List agreements with optional filters | Host, Beekeeper, ApiaryManager, PlatformOps |
| POST | `/api/agreements/{id}/sign` | Host signs the agreement; pins the liability clause version | Host |
| POST | `/api/agreements/{id}/propose-amendment` | Propose a share amendment (OCC-guarded) | PlatformOps |
| POST | `/api/agreements/{id}/accept-amendment` | Host accepts the pending amendment | Host |
| POST | `/api/agreements/{id}/reject-amendment` | Host rejects the pending amendment | Host |
| POST | `/api/agreements/{id}/terminate` | Terminate an agreement | Host, PlatformOps |
| POST | `/api/hives` | Install a hive on a site under an agreement | ApiaryManager |
| GET | `/api/hives/{id}` | Read a hive with current posture fields | Host, Beekeeper, ApiaryManager, PlatformOps |
| GET | `/api/hives` | List hives with filters | Host, Beekeeper, ApiaryManager, PlatformOps |
| POST | `/api/hives/{id}/split` | Split a strong hive into a child on the same site | ApiaryManager |
| POST | `/api/hives/{id}/mark-dead` | Record colony death | ApiaryManager |
| POST | `/api/inspections` | Record a field inspection (DRAFT) | Beekeeper |
| GET | `/api/inspections/{id}` | Read an inspection | Host, Beekeeper, ApiaryManager, PlatformOps |
| GET | `/api/inspections` | List inspections with filters | Host, Beekeeper, ApiaryManager, PlatformOps |
| POST | `/api/inspections/{id}/submit` | Submit or resubmit an inspection for verification | Beekeeper |
| POST | `/api/inspections/{id}/verify` | Verify a submitted inspection (segregation of duties) | ApiaryManager |
| POST | `/api/inspections/{id}/return` | Return a submitted inspection for correction | ApiaryManager |
| POST | `/api/treatments` | Schedule a mite treatment | ApiaryManager |
| GET | `/api/treatments/{id}` | Read a treatment | Host, Beekeeper, ApiaryManager, PlatformOps |
| GET | `/api/treatments` | List treatments with filters | Host, Beekeeper, ApiaryManager, PlatformOps |
| POST | `/api/treatments/{id}/start` | Start a scheduled treatment | Beekeeper |
| POST | `/api/treatments/{id}/complete` | Complete an in-progress treatment | Beekeeper |
| POST | `/api/harvests` | Record a honey harvest (net_kg computed immediately) | Beekeeper |
| GET | `/api/harvests/{id}` | Read a harvest | Host, Beekeeper, ApiaryManager, PlatformOps |
| GET | `/api/harvests` | List harvests with filters | Host, Beekeeper, ApiaryManager, PlatformOps |
| POST | `/api/harvests/{id}/approve` | Approve a recorded harvest (segregation of duties) | ApiaryManager |
| POST | `/api/harvests/{id}/void` | Void a recorded or approved harvest before finalization | ApiaryManager |
| GET | `/api/allocations/{id}` | Read an allocation | Host, Beekeeper, ApiaryManager, PlatformOps |
| GET | `/api/allocations` | List allocations with filters | Host, Beekeeper, ApiaryManager, PlatformOps |
| POST | `/api/allocations/{id}/distribute` | Distribute a finalized allocation | PlatformOps |
| POST | `/api/swarm-events` | Host reports a swarm on a site they own | Host |
| GET | `/api/swarm-events/{id}` | Read a swarm event (lazy expiry applied) | Host, Beekeeper, ApiaryManager, PlatformOps |
| GET | `/api/swarm-events` | List swarm events with filters | Host, Beekeeper, ApiaryManager, PlatformOps |
| POST | `/api/swarm-events/{id}/dispatch` | Dispatch the calling beekeeper to a reported swarm | Beekeeper |
| POST | `/api/swarm-events/{id}/capture` | Capture the swarm, creating a new hive | Beekeeper |
| POST | `/api/swarm-events/{id}/mark-lost` | Mark a dispatched swarm as lost | Beekeeper |
| POST | `/api/removal-jobs` | Host requests removal of a hive | Host |
| GET | `/api/removal-jobs/{id}` | Read a removal job | Host, Beekeeper, ApiaryManager, PlatformOps |
| GET | `/api/removal-jobs` | List removal jobs with filters | Host, Beekeeper, ApiaryManager, PlatformOps |
| POST | `/api/removal-jobs/{id}/approve` | Manager decision on a requested removal | ApiaryManager |
| POST | `/api/removal-jobs/{id}/schedule` | Schedule an approved removal (48h notice, 2h crew buffer) | ApiaryManager |
| POST | `/api/removal-jobs/{id}/complete` | Complete a scheduled removal; the hive becomes REMOVED | Beekeeper |
| POST | `/api/removal-jobs/{id}/cancel` | Cancel a non-terminal removal | Host, PlatformOps |
| POST | `/api/subscriptions` | Create a host subscription and issue the first invoice | PlatformOps |
| GET | `/api/subscriptions/{id}` | Read a subscription (projected overwinter credit computed live) | Host, Beekeeper, ApiaryManager, PlatformOps |
| GET | `/api/subscriptions` | List subscriptions with filters | Host, Beekeeper, ApiaryManager, PlatformOps |
| POST | `/api/subscriptions/{id}/change-plan` | Schedule a plan change effective next rollover (OCC-guarded) | Host |
| POST | `/api/subscriptions/{id}/cancel` | Cancel a subscription (zero balance required) | Host |
| GET | `/api/invoices/{id}` | Read an invoice | Host, Beekeeper, ApiaryManager, PlatformOps |
| GET | `/api/invoices` | List invoices with filters | Host, Beekeeper, ApiaryManager, PlatformOps |
| POST | `/api/invoices/{id}/pay` | Pay an OPEN or OVERDUE invoice | Host, PlatformOps |
| POST | `/api/invoices/{id}/void` | Void an unpaid invoice | PlatformOps |
| POST | `/api/enrollments` | Enroll a host in an education course | Host |
| GET | `/api/enrollments/{id}` | Read an enrollment | Host, Beekeeper, ApiaryManager, PlatformOps |
| GET | `/api/enrollments` | List enrollments with filters | Host, Beekeeper, ApiaryManager, PlatformOps |
| POST | `/api/enrollments/{id}/complete` | Record the quiz result (80 or more completes) | PlatformOps |
| POST | `/api/incidents` | Report a sting/liability incident on a site | Host, Beekeeper, ApiaryManager |
| GET | `/api/incidents/{id}` | Read an incident | Host, Beekeeper, ApiaryManager, PlatformOps |
| GET | `/api/incidents` | List incidents with filters | Host, Beekeeper, ApiaryManager, PlatformOps |
| POST | `/api/incidents/{id}/resolve` | Resolve an incident; AT_FAULT decrements host reputation | ApiaryManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| ERR_MISSING_OR_INVALID_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 400 |
| ERR_HIVE_NOT_OPERABLE | 400 |
| ERR_AGREEMENT_NOT_ACTIVE | 400 |
| ERR_INSPECTION_NOT_SUBMITTED | 400 |
| ERR_SUBSCRIPTION_NOT_ACTIVE | 400 |
| ERR_INVOICE_NOT_PAYABLE | 400 |
| ERR_INVOICE_NOT_VOIDABLE | 400 |
| ERR_SWARM_NOT_ACTIONABLE | 400 |
| ERR_REMOVAL_NOT_ACTIONABLE | 400 |
| ERR_ALLOCATION_NOT_DISTRIBUTABLE | 400 |
| ERR_SEASON_NOT_CLOSABLE | 409 |
| ERR_ENROLLMENT_NOT_COMPLETABLE | 400 |
| ERR_WAIVER_CURRENT_REQUIRED | 400 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_HIVE_QUARANTINED | 400 |
| ERR_WITHDRAWAL_WINDOW_ACTIVE | 400 |
| ERR_SITE_BLOCKED | 400 |
| ERR_SITE_CAPACITY_EXCEEDED | 409 |
| ERR_AGREEMENT_WINDOW_OVERLAP | 409 |
| ERR_TREATMENT_WINDOW_OVERLAP | 409 |
| ERR_CREW_SCHEDULE_CONFLICT | 409 |
| ERR_DUPLICATE_SUBSCRIPTION | 409 |
| ERR_COURSE_PREREQUISITE_NOT_MET | 400 |
| ERR_SITE_HAS_OPEN_INCIDENTS | 409 |
| ERR_AGREEMENT_HAS_LIVE_HIVES | 409 |
| ERR_INSPECTION_STALE | 400 |
| ERR_REMOVAL_NOTICE_TOO_SHORT | 400 |
| ERR_HOST_NOT_ACTIVE | 400 |
| ERR_OUTSTANDING_BALANCE | 400 |
| ERR_HOST_REPUTATION_TOO_LOW | 400 |
| ERR_STALE_VERSION | 412 |

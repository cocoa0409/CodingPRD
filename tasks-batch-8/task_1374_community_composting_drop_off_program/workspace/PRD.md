# Community Composting Drop-Off API — Product Requirements Document

## 1. Introduction

Municipal composting programs live or die on trust: residents must trust that their food scraps actually become compost rather than landfill tonnage, and the city must trust that the tonnage numbers it reports are defensible under audit. This document specifies the API for a **Community Composting Drop-Off Program** platform — a system that runs a network of neighborhood drop-off sites, administers a participant registration and access-code/bucket program, tracks contamination findings and the feedback loop back to participants, schedules collection routes from drop sites to a processing partner, distributes finished compost back to participants, handles odor and vector complaints against a service-level clock, and produces certified tonnage-diversion reports for the municipality.

The platform is organized around a `Program` aggregate: everything — sites, host agreements, material categories, participants, routes, partners, distributions, and diversion reports — is scoped to a program and its reporting `fiscal_year`. Two design commitments shape the whole surface. First, **posture-driven gating**: every site continuously derives a posture (`OPEN`, `WATCH`, `SUSPENDED`, or `CLOSED`) from its stored mass, open contamination findings, unresolved complaints, and host-agreement coverage, and that posture gates whether drops are accepted at all. Second, **auditability with segregation of duties**: diversion reports are drafted and certified by different auditors, contamination findings flow from independent municipal auditors rather than site staff, and credit ledgers conserve exactly — every credit granted is traceable through redemption, refund, or expiry.

A single logical clock governs every temporal rule in the system — seasonal material windows, agreement terms, complaint SLAs, grant expiries, and credit expiry. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock time, and it advances only when an authorized operator explicitly sets it. Deterministic time is a testability and audit requirement, not a convenience.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the caller's role. If either header is missing, or the role value is not one of the recognized roles below, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the role is recognized but not permitted for the target endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The recognized roles, spelled exactly, are:

- `Anonymous` — unauthenticated caller; may register participants, verify registrations, and file complaints.
- `ProgramAdmin` — the city program operator; owns configuration, site lifecycle, host agreements, participant discipline, contamination feedback, distributions, complaint handling, and the ops-run checkpoint.
- `SiteHost` — host of a drop-off site; audits drops and accepts or rejects them.
- `Participant` — a registered resident; records drops and requests compost allocations.
- `RouteOperator` — the collection contractor; plans and executes routes and their stops.
- `ProcessingPartner` — the compost processor; closes batches with measured contamination.
- `MunicipalAuditor` — the city auditor; opens and dismisses contamination reports, reopens complaints, and generates and certifies diversion reports.

The `X-User-ID` header is bound to identity differently per role. When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting `Participant` record; ownership checks on any resource that references a `Participant` compare the resource's foreign-key field (for example, a drop's `participant_id`) to `X-User-ID`. Likewise, when `X-User-Role` is `ProcessingPartner`, `X-User-ID` is the `id` of the acting `ProcessingPartner` record, and ownership checks compare against `X-User-ID` on resources that reference a `ProcessingPartner`. When `X-User-Role` is `Anonymous`, `ProgramAdmin`, `SiteHost`, `RouteOperator`, or `MunicipalAuditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `auditor_id` on a `ContaminationReport` or as `certified_by` on a `DiversionReport`, where a scaffold-defined transition writes it) but does not compare it to any entity's `id` for ownership.

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

### 2.3. Pagination

All list endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, must be at least 1, and may be at most 100; `offset` defaults to 0. List responses include the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object. Unless a more specific ordering is stated for an individual workflow, every list endpoint returns resources sorted by `created_at` ascending.

### 2.4. Common Resource Properties and the Logical Clock

Most resources share four common properties: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation; and `version`, an integer starting at 1 that increments by exactly 1 on every mutation of the resource. Two resource kinds do **not** carry the full set: `DistributionAllocation` and `DiversionReport` carry only `id` and `created_at` — both `updated_at` and `version` are absent on them, and no optimistic-concurrency field can therefore be taken on their own writes (allocations instead gate on the parent distribution's version, as described below).

All temporal rules in this document — agreement terms, grant expiries, complaint SLAs, credit ageing, seasonal windows, report periods — are evaluated against the server's **logical clock**, never wall-clock time. The logical clock starts at exactly `2026-08-01T00:00:00Z` at server startup. A `ProgramAdmin` may advance it through an admin-only test-driving capability that accepts a `to_iso8601` instant and responds with the new `now` value; this capability is the only way time moves.

### 2.5. Nested Resource Retrieval and Optimistic Concurrency Control

Nested resource URLs are validated left-to-right: the program id first, then the site or other intermediate id, then the child id. The first id that does not exist — or that does not exist within the scope established by the ids to its left — produces `ERR_NOT_FOUND` (HTTP 404); ids further to the right are not examined once an earlier id has failed.

Three write endpoints additionally enforce optimistic concurrency control against the parent aggregate they mutate:

- Recording a drop at a site requires the request to carry `expected_site_version`, holding the `version` of the parent `Site` the client last observed. If the site's current `version` has advanced since that read — because another writer recorded a drop, a pickup completed, or a posture-affecting report or complaint landed — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot write against a stale view of `stored_kg` or posture.
- Adding a stop to a route requires `expected_route_version`, holding the last-observed `version` of the parent `CollectionRoute`. If the route's version has advanced — a prior writer added a stop or dispatched the route — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the client's capacity and sequence view.
- Requesting an allocation against a distribution requires `expected_distribution_version`, holding the last-observed `version` of the parent `CompostDistribution`. If the distribution's version has advanced because a prior request consumed part of the pool, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the client's view of the remaining pool.

Endpoints not named above do not take any expected-version field.

### 2.6. Precision, Rounding, and Interval Conventions

All kilogram masses and percentages in the system are carried at 2 decimal places of precision, using round-half-up at every rounding step. Where a rule says a value is "rounded to 0.01", it means round-half-up to two decimal places. Bucket credits, by contrast, are always integers; the credit rounding rule (round-half-up applied independently to provisional and final masses) is described with the drop-acceptance workflow.

Interval comparisons throughout the system use half-open semantics on the right: an agreement term runs from its inclusive `term_start` to its exclusive `term_end`, a route window runs from its inclusive `scheduled_start` to its exclusive `scheduled_end`, and a report period runs from its inclusive `period_start` to its exclusive `period_end`. Two intervals conflict only when each one's start falls strictly before the other's end; touching boundaries — where one interval's end equals the other's start — never conflict.

### 2.7. Site Posture: The Derived Gate

A site carries two parallel state dimensions: an operator-driven `status` (`ONBOARDING`, `OPERATIONAL`, `DECOMMISSIONED`) and a fully derived `posture` (`OPEN`, `WATCH`, `SUSPENDED`, `CLOSED`). Posture is never set directly; it is recomputed after every posture-relevant event — a drop recorded, a contamination report opened, resolved, or dismissed, a complaint filed, resolved, or reopened, a stop collected, skipped, or cancelled, a host agreement expired or terminated, an ops-run checkpoint, and program suspension or reactivation.

The recomputation evaluates a fixed sequence of tiers, and the first tier that matches wins. The evaluation order is pinned and must not be reordered:

1. **Hard override.** If the site's `status` is not `OPERATIONAL`, or the owning program's `status` is not `ACTIVE`, posture is `CLOSED`.
2. **Agreement coverage.** Otherwise, if the site's `host_agreement_id` is null — no currently effective agreement — posture is `CLOSED`; a site with no active agreement cannot accept drops.
3. **Physical capacity.** Otherwise, if the site's available on-site mass — `stored_kg` minus `pending_pickup_kg` — is greater than or equal to `capacity_kg`, posture is `SUSPENDED`. The boundary itself triggers: available mass exactly equal to capacity is full.
4. **Severe contamination.** Otherwise, if the number of open contamination reports of severity `MAJOR` or `CRITICAL` at the site is at least twice the program's `posture_contam_threshold`, posture is `SUSPENDED`.
5. **Watch conditions.** Otherwise, posture is `WATCH` if any one of three conditions holds: available on-site mass is at least 80 percent of `capacity_kg` (the capacity figure is rounded up to a whole kilogram before comparison, so the threshold is the ceiling of 0.8 times `capacity_kg`); the count of open contamination reports at the site is at least the program's `posture_contam_threshold`; or the number of unresolved complaints filed within the rolling 14-day window ending at the current logical clock is at least the program's `posture_complaint_threshold`.
6. Otherwise, posture is `OPEN`.

For this calculation, an **open** contamination report is one whose `status` is `OPEN` or `FEEDBACK_SENT`; the severe count additionally restricts to severity `MAJOR` or `CRITICAL`. An **unresolved** complaint is one whose `status` is `OPEN`, `ACKNOWLEDGED`, or `REOPENED`, with `reported_at` falling within the last 14 days of the current logical clock, the window inclusive of both endpoints.

Posture gates drop acceptance directly (detailed in §3.4): a site at `OPEN` accepts drops normally, a site at `WATCH` accepts only drops of at most 5 kg gross, and a site at `SUSPENDED` or `CLOSED` rejects every drop with `ERR_SITE_POSTURE_BLOCKS_DROP` (HTTP 409).

### 2.8. Conserved Ledgers: Site Mass and Bucket Credits

Two quantities in the system are conserved ledgers whose value at any moment is fully determined by underlying events, and implementations must keep them reconciled event-by-event rather than recomputing lazily.

**Site mass.** A site's `stored_kg` equals the sum of the net mass of every live drop event at the site — provisional net while a drop is pending or accepted-but-unreconciled, final net once a batch has reconciled it — minus the sum of `actual_pickup_kg` over all `COLLECTED` stops at the site. A drop that is rejected subtracts its provisional mass, because that mass was counted at drop time but is never accepted. A site's `pending_pickup_kg` equals the sum of `planned_pickup_kg` over all `SCHEDULED` stops at the site; it rises when a stop is added and falls when the stop is collected, skipped, or cancelled.

**Bucket credits.** Each participant's `bucket_credit_balance` equals `bucket_credits_granted_total` minus `bucket_credits_redeemed_total` minus `bucket_credits_expired_total` at all times. Credits enter through confirmed drops, leave through distribution redemption (or refund), and expire of old age: at each ops-run checkpoint, credits granted more than 365 days earlier — measured by the granting drop event's `occurred_at` — and not yet redeemed expire into `bucket_credits_expired_total`. Both redemption and expiry consume the oldest granted credits first (first-in-first-out); ties between grants are broken by the granting drop event's `created_at`, earliest first.

### 2.9. Validation Order and Soft Deletion

When several validation rules could reject the same request, the server evaluates them in a fixed priority order, and the first failure determines the error returned. The order is:

1. Authentication context: `X-User-ID` and `X-User-Role` present and the role recognized — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). This applies to every endpoint.
2. Authorization: the role is permitted for the target endpoint — otherwise `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). This applies to every endpoint.
3. Existence: path ids exist, validated left-to-right — otherwise `ERR_NOT_FOUND` (HTTP 404). This applies to every nested endpoint.
4. Stale-version check: on the three concurrency-guarded writes named in §2.5, the expected parent version matches the parent's current `version` — otherwise `ERR_STALE_VERSION` (HTTP 412).
5. From-state: the target resource is in a valid from-state for the requested transition — otherwise `ERR_INVALID_STATE` (HTTP 409). This applies to every state-transition endpoint.
6. Posture gate on drop creation: site posture must be `OPEN` (or `WATCH` with a drop of at most 5 kg gross) — otherwise `ERR_SITE_POSTURE_BLOCKS_DROP` (HTTP 409).
7. Material acceptance on drop creation: the material category must be active and within its seasonal window — otherwise `ERR_MATERIAL_NOT_ACCEPTED` (HTTP 409).
8. Access-grant validity on drop creation: the grant must be `ACTIVE`, belong to the participant, reference the site, and have bucket headroom — otherwise `ERR_ACCESS_GRANT_INVALID` (HTTP 409).
9. Drop timing: `occurred_at` must not be in the future and must fall within the site's agreement term — otherwise `ERR_DROP_OUTSIDE_AGREEMENT_TERM` (HTTP 409).
10. Route window sanity at dispatch: `scheduled_end` after `scheduled_start` and no overlapping dispatched route at the same partner — otherwise `ERR_PARTNER_DOUBLE_BOOKED` (HTTP 409).
11. Load bounds: `assigned_load_kg` within `vehicle_capacity_kg` at dispatch, and stop-collection actuals bounded by site available mass — otherwise `ERR_ROUTE_OVER_CAPACITY` (HTTP 409) or `ERR_PICKUP_EXCEEDS_AVAILABLE` (HTTP 409) as applicable.
12. Allocation affordability: `credits_redeemed` within the participant's balance and `requested_kg` positive — otherwise `ERR_INSUFFICIENT_BUCKET_CREDITS` (HTTP 409).
13. Segregation of duties at certification: the certifier differs from the report's creator — otherwise `ERR_SOD_SAME_USER` (HTTP 403).

A malformed request body, a missing required field, or an enum value outside its declared set is rejected with `ERR_INVALID_REQUEST` (HTTP 400) regardless of the rules above.

Sites support soft deletion: archiving sets a site's `archived` flag to true, after which the site is excluded from default site listings. Callers who need archived sites pass `include_archived` on the listing. Archiving is only meaningful for decommissioned sites, and a site containing an archived flag still participates in historical lookups by id.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Program

A `ProgramAdmin` begins by creating a program with a `name` and a `fiscal_year`. Optional tuning knobs accepted at creation are `posture_contam_threshold` (the number of open contamination reports at a site that forces posture `WATCH`, defaulting to 3, with twice that number of severe reports forcing `SUSPENDED`), `posture_complaint_threshold` (the number of unresolved complaints in the rolling 14-day window that forces `WATCH`, defaulting to 2), and `diversion_credit_rate` (the bucket-credit points granted per net kilogram of accepted drop, defaulting to 1.0). A new program starts in `DRAFT` status with its `ops_run_index` at 0, and its program-wide totals `total_diverted_kg` and `total_contamination_kg` at 0.

Activation is deliberately gated. Moving a program from `DRAFT` to `ACTIVE` requires at least one site already in `OPERATIONAL` status under the program — otherwise the activation is rejected with `ERR_PROGRAM_NO_OPERATIONAL_SITE` (HTTP 409) — and at least one material category with `active` set to true — otherwise `ERR_PROGRAM_NO_MATERIAL_CATEGORY` (HTTP 409). Material categories define what the program accepts. Creating one takes a `code` unique within the program (for example, FOOD_SCRAPS or YARD_WASTE), a human-readable `description`, the seasonal window bounds `accepted_start_month_day` and `accepted_end_month_day` (whose semantics are defined with the drop workflow in §3.4), a `contamination_sensitivity` of `LOW`, `MEDIUM`, or `HIGH` — which drives how readily findings against that material escalate — and an optional `active` flag defaulting to true. A `ProgramAdmin` may later patch a category's `active` flag or `description`; an inactive category is rejected at intake. Category listings support the `active` filter.

An active program may be suspended at will: suspension moves it to `SUSPENDED` and, as a cascade, forces every site's posture to `SUSPENDED` for as long as the program remains suspended. Re-activation from `SUSPENDED` returns the program to `ACTIVE` and recomputes every site's posture from scratch. Closing a program is terminal: the transition from `ACTIVE` to `CLOSED` is allowed only when no site remains in `OPERATIONAL` status, failing with `ERR_PROGRAM_HAS_OPERATIONAL_SITES` (HTTP 409) otherwise.

Programs are readable by every authenticated role.

### 3.2. Sites and Their Host Agreements

Sites are the physical footprint of the program. Creating a site takes a `name`, an `address`, and a `capacity_kg` — the maximum on-site stored kilograms before posture degrades. A new site starts in `ONBOARDING` status with posture `CLOSED` and `stored_kg` at 0. Site listings exclude archived sites by default and support `status` filtering alongside `limit`, `offset`, and `include_archived`.

Before a site can operate, the city must paper the site host. A `SiteHostAgreement` is created for a program with the covered `site_id`, the host's legal `host_name`, a `term_start` (inclusive), a `term_end` (exclusive), and an optional `cure_period_days` defaulting to 14. New agreements start in `DRAFT`. Activation moves an agreement from `DRAFT` to `ACTIVE` and enforces three checks: `term_end` must be after `term_start`, failing with `ERR_INVALID_TERM` (HTTP 409); no other `ACTIVE` agreement for the same site may have a term overlapping this one, failing with `ERR_AGREEMENT_OVERLAP` (HTTP 409) — overlap here follows the half-open rule of §2.6, so a renewal whose `term_start` exactly equals the outgoing agreement's `term_end` is permitted; and `term_end` must be strictly after the current logical clock, failing with `ERR_AGREEMENT_ALREADY_EXPIRED` (HTTP 409) for an agreement whose term has already run out. On activation, when the agreement's `site_id` matches a site and no other `ACTIVE` agreement covers that site, the site's `host_agreement_id` is set to point at this agreement.

Commissioning transitions a site from `ONBOARDING` to `OPERATIONAL`. It requires an `ACTIVE` host agreement covering the site — otherwise `ERR_SITE_NO_ACTIVE_AGREEMENT` (HTTP 409) — and requires the owning program to be `ACTIVE`. As a side effect, the site's posture is computed for the first time; a freshly commissioned site with zero stored mass and no open reports lands at `OPEN`.

Decommissioning moves a site from `OPERATIONAL` to `DECOMMISSIONED` and enforces three preconditions: `stored_kg` must be exactly 0, failing with `ERR_SITE_NOT_EMPTY` (HTTP 409); no `RouteStop` in `SCHEDULED` status may exist for the site, failing with `ERR_SITE_HAS_SCHEDULED_PICKUPS` (HTTP 409); and no `AccessGrant` in `ACTIVE` status may reference the site, failing with `ERR_SITE_HAS_ACTIVE_GRANTS` (HTTP 409). On decommission, the site's currently `ACTIVE` host agreement is transitioned to `TERMINATED` and the site's `host_agreement_id` is cleared; the site's posture becomes `CLOSED`. A decommissioned site may then be archived, setting `archived` to true.

Host agreements have their own discipline lifecycle after activation. Issuing a breach notice moves an `ACTIVE` agreement to `BREACH_NOTICED` and stamps `breach_noticed_at` with the current logical clock. Curing the breach returns the agreement to `ACTIVE`, but only while the cure window is open: the current logical clock must be strictly earlier than `breach_noticed_at` plus `cure_period_days`, failing with `ERR_CURE_PERIOD_ELAPSED` (HTTP 409) once the window has closed; a successful cure clears `breach_noticed_at` back to null. Termination from `BREACH_NOTICED` is the mirror image: it requires the current logical clock to be at or after `breach_noticed_at` plus `cure_period_days`, failing with `ERR_CURE_PERIOD_NOT_ELAPSED` (HTTP 409) while the host still has time to cure. Termination directly from `ACTIVE` carries no such precondition. In either termination path, if the terminating agreement is the one referenced by its site's `host_agreement_id`, that link is cleared and the site's posture is recomputed — which, with no covering agreement, drives the posture to `CLOSED` under §2.7's agreement-coverage tier. Finally, the ops-run checkpoint transitions any `ACTIVE` agreement whose `term_end` has been reached to `EXPIRED`, clears the site's `host_agreement_id` if it points at the expired agreement, and recomputes an `OPERATIONAL` site's posture, dropping it to `CLOSED` when no other `ACTIVE` agreement covers the site.

Agreement listings support filtering by `site_id` and `status`; agreements are readable by `ProgramAdmin`, `SiteHost`, and `MunicipalAuditor`.

### 3.3. Participants, Access Grants, and the Bucket Program

Residents join a program through self-registration: an `Anonymous` caller supplies `email`, `full_name`, and `household_size` (the household size later used in distribution fair-share weighting). The email must be unique within the program. A new participant starts in `PENDING_VERIFY` status, and the server mints a `verification_token` at registration. Verification — also an `Anonymous` operation — presents the `verification_token`; a mismatch is rejected with `ERR_INVALID_VERIFICATION_TOKEN` (HTTP 400). Successful verification moves the participant to `ACTIVE` and clears the token.

Participant discipline is graduated. Suspending an `ACTIVE` participant moves them to `SUSPENDED`, increments `suspension_count` by 1, and revokes every `ACTIVE` access grant the participant holds — but when the increment brings `suspension_count` to 3, the participant instead transitions directly to `DEACTIVATED`: the third suspension is permanent. Reinstating a `SUSPENDED` participant returns them to `ACTIVE` and is blocked once `suspension_count` has reached 3, failing with `ERR_PARTICIPANT_PERMANENTLY_DEACTIVATED` (HTTP 409). Deactivation, from either `ACTIVE` or `SUSPENDED`, requires that the participant hold no `REQUESTED` distribution allocations — otherwise `ERR_PARTICIPANT_HAS_PENDING_ALLOCATIONS` (HTTP 409) — and on success revokes all `ACTIVE` access grants and folds the participant's entire `bucket_credit_balance` into `bucket_credits_expired_total`, zeroing the balance through the expiry invariant of §2.8. Participant listings are restricted to `ProgramAdmin` and `MunicipalAuditor` and support `status` filtering; a participant may read their own record.

Access to physical sites is mediated by `AccessGrant` records. A `ProgramAdmin` issues a grant for a participant with a `site_id`, a `bucket_quota` (the number of buckets the participant may hold at once at that site), and an `expires_at`. The grant starts `ACTIVE`; the server mints an `access_code` — an 8-character code unique per site among `ACTIVE` grants — and `buckets_checked_out` starts at 0. Revoking a grant moves it to `REVOKED` and is blocked while `buckets_checked_out` is greater than 0, failing with `ERR_BUCKETS_STILL_OUT` (HTTP 409); suspension and deactivation cascades bypass this check when they revoke grants. Grants also age out: at each ops-run checkpoint, any `ACTIVE` grant whose `expires_at` has been reached transitions to `EXPIRED`, and if buckets are still checked out at that moment the system automatically opens a `ContaminationReport` of severity `MINOR` on the grant's site documenting the overdue buckets. Grant listings support `status` filtering and are readable by `ProgramAdmin`, the owning `Participant`, and `MunicipalAuditor`.

### 3.4. Drop Events, Contamination, and Participant Feedback

The heart of the program is the drop. A `Participant` records a drop at a site by presenting `participant_id`, the `access_grant_id` used for entry, the `material_category_id` of the material, the scale reading `gross_weight_kg` (which must be greater than 0), an estimate `contamination_kg` (which must be at least 0 and no greater than `gross_weight_kg`), the `occurred_at` moment the drop physically occurred, and — per §2.5 — `expected_site_version`.

Four business checks guard acceptance, evaluated after the generic checks of §2.9 in the order stated there: posture first, then material, then grant, then timing. Posture gating follows §2.7 — `OPEN` accepts, `WATCH` accepts only drops whose gross weight is at most 5 kg, and `SUSPENDED` or `CLOSED` reject with `ERR_SITE_POSTURE_BLOCKS_DROP`. The material check requires the category to be active and inside its seasonal acceptance window at drop time; each category defines an annual window through `accepted_start_month_day` and `accepted_end_month_day`, both `MM-DD` strings, inclusive on both ends, and the window may wrap the year boundary: when the start month-day is not after the end month-day, the current date's month-day must fall between them inclusive; when the start is after the end (a window wrapping December into January), the current month-day must be at or after the start **or** at or before the end. The current month-day is taken from the logical clock. An inactive category or an out-of-season date fails with `ERR_MATERIAL_NOT_ACCEPTED`. The grant check requires the access grant to be `ACTIVE`, to belong to the presenting participant, to reference this site, and to have `buckets_checked_out` below `bucket_quota`; any failure is `ERR_ACCESS_GRANT_INVALID`. Finally, `occurred_at` must not be after the current logical clock and must fall within the site's host agreement term, inclusive of `term_start` and exclusive of `term_end`; violations fail with `ERR_DROP_OUTSIDE_AGREEMENT_TERM`.

On acceptance into the system, the drop's `provisional_net_kg` is computed as `gross_weight_kg` minus `contamination_kg`, rounded half-up to two decimal places. The drop starts with `verification_state` `PENDING_AUDIT` and `credit_state` `UNCREDITED`, its `processing_batch_id` and `final_net_kg` null. Recording the drop immediately adds its `provisional_net_kg` to the site's `stored_kg`, recomputes the site's posture, and increments the site's `version` by 1 — which is precisely what invalidates any other client's `expected_site_version`. Drop listings support filtering by `participant_id`, `verification_state`, and `credit_state`.

The audit loop runs on two parallel dimensions that never collapse into one: `verification_state` (`PENDING_AUDIT`, `ACCEPTED`, `FLAGGED_CONTAMINATED`, `REJECTED`) and `credit_state` (`UNCREDITED`, `PROVISIONALLY_CREDITED`, `FINALLY_CREDITED`, `REVOKED`). A `SiteHost` accepts a pending drop, provided the containing site is not archived; acceptance moves `verification_state` from `PENDING_AUDIT` to `ACCEPTED`, flips `credit_state` from `UNCREDITED` to `PROVISIONALLY_CREDITED`, and grants credits: the participant's `bucket_credit_balance` increases by the provisional net kilograms multiplied by the program's `diversion_credit_rate`, rounded half-up to a whole credit, and `bucket_credits_granted_total` increases by the same amount.

Contamination findings come from `MunicipalAuditor` operators, never site staff. Opening a contamination report takes an optional `drop_event_id` (null for site-wide audits), the `auditor_id` of the recording auditor, a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`, and a free-text `finding_note`. The report starts `OPEN`; if it references a drop, that drop's `verification_state` automatically moves from `PENDING_AUDIT` to `FLAGGED_CONTAMINATED` while its `credit_state` stays `UNCREDITED` until the finding is resolved. The site's posture is recomputed, since the open-report count just rose.

Feedback closes the loop with the resident. Sending feedback on a report requires the report to reference a drop — site-wide audit reports have no participant to notify, and the attempt fails with `ERR_FEEDBACK_REQUIRES_DROP_LINK` (HTTP 409) — and moves the report from `OPEN` to `FEEDBACK_SENT`, stamping `feedback_sent_at` with the current logical clock. From `FEEDBACK_SENT`, resolution moves the report to `RESOLVED`; if the linked drop was sitting at `FLAGGED_CONTAMINATED`, it flips to `ACCEPTED` with exactly the same credit side effects as a direct acceptance — provisional credits granted per the rounding rule above — and the site's posture recomputes as its open-report count falls. A report in `OPEN` may be resolved directly only when its `drop_event_id` is null; site-wide audit reports may resolve without feedback, and the site's posture recomputes. Dismissal, a `MunicipalAuditor` prerogative, moves a report from `OPEN` to `DISMISSED`; when the dismissed report has severity `CRITICAL` and references a drop, the linked drop transitions to `REJECTED`. Report listings support `status` and `severity` filtering.

Rejection — whether by dismissal of a `CRITICAL` report or by a `SiteHost` explicitly rejecting a flagged drop — moves `verification_state` to `REJECTED`, subtracts the drop's `provisional_net_kg` from the site's `stored_kg` (the mass was never truly accepted), and flips `credit_state` to `REVOKED`.

### 3.5. Collection Routes and Processing Batches

Getting material off site is the `RouteOperator`'s domain, and it starts with partners. A `ProgramAdmin` registers a `ProcessingPartner` with a `name`, a daily `intake_capacity_kg_per_day`, a `yield_ratio` — finished compost kilograms produced per net input kilogram, strictly greater than 0 and at most 1 — a `contamination_reject_threshold_pct`, and an optional `active` flag defaulting to true. Inactive partners cannot be assigned new routes.

Planning a route takes a `route_code` unique within the program, a `vehicle_capacity_kg`, the `processing_partner_id` that will receive the loads, and the `scheduled_start` and `scheduled_end` of the departure and return window. A new route starts `PLANNED` with `assigned_load_kg` at 0. Stops are added to a planned route one at a time; each stop takes a `site_id`, a `planned_pickup_kg`, a `stop_sequence` unique within the route, and — per §2.5 — `expected_route_version`. Adding a stop creates it in `SCHEDULED` status, adds its `planned_pickup_kg` to both the site's `pending_pickup_kg` and the route's `assigned_load_kg`, recomputes the site's posture, and increments the route's `version` by 1. Stop listings support `site_id` and `status` filters; route listings support `status` and `processing_partner_id` filters.

Dispatching a route moves it from `PLANNED` to `DISPATCHED` and enforces four preconditions: at least one stop must be in `SCHEDULED` status, failing with `ERR_ROUTE_HAS_NO_STOPS` (HTTP 409); `assigned_load_kg` must not exceed `vehicle_capacity_kg`, failing with `ERR_ROUTE_OVER_CAPACITY` (HTTP 409); the route's partner must be active, failing with `ERR_PARTNER_INACTIVE` (HTTP 409); and no other `DISPATCHED` route with the same partner may have a time window overlapping this one, failing with `ERR_PARTNER_DOUBLE_BOOKED` (HTTP 409). Overlap follows the half-open rule of §2.6: windows conflict only when each route's start falls strictly before the other's end, so a route departing exactly when another returns — one's `scheduled_start` equal to the other's `scheduled_end` — is permitted.

On the road, each `SCHEDULED` stop is worked to a terminal state. Collecting a stop requires the parent route to be `DISPATCHED` — otherwise `ERR_ROUTE_NOT_DISPATCHED` (HTTP 409) — and takes the driver-recorded `actual_pickup_kg`, which must be at least 0 and no greater than the site's available mass defined as `stored_kg` plus `pending_pickup_kg`; an out-of-bounds figure fails with `ERR_PICKUP_EXCEEDS_AVAILABLE` (HTTP 409). Collection records the actual figure and moves the stop to `COLLECTED`. Skipping a stop likewise requires the route to be `DISPATCHED`; it moves the stop to `SKIPPED`, releases the site's `pending_pickup_kg` by the stop's `planned_pickup_kg`, and recomputes posture. Cancelling a stop directly is only allowed while the route is still `PLANNED` — otherwise `ERR_ROUTE_NOT_PLANNED` (HTTP 409) — with the same pending-mass release and posture recompute.

Completing a route requires every stop to have reached `COLLECTED`, `SKIPPED`, or `CANCELLED` — any stop still `SCHEDULED` fails with `ERR_ROUTE_STOPS_PENDING` (HTTP 409). Completion moves the route to `COMPLETED` and settles the books per stop: for each `COLLECTED` stop, the site's `stored_kg` decreases by `actual_pickup_kg` and its `pending_pickup_kg` decreases by `planned_pickup_kg`, with a posture recompute. Completion also opens a `ProcessingBatch` at the route's partner whose `input_gross_kg` is the sum of `actual_pickup_kg` across the route's `COLLECTED` stops; a route completed with zero collected stops opens no batch. Cancelling a route — allowed from `PLANNED` — moves it to `CANCELLED`, cascades every `SCHEDULED` stop to `CANCELLED`, releases each stop's `planned_pickup_kg` from its site's `pending_pickup_kg`, and recomputes posture at each affected site.

The batch is where the partner's measurements replace participant estimates. Closing a batch, a `ProcessingPartner` operation, supplies the partner-measured `measured_contamination_kg`. The batch's `measured_net_kg` is `input_gross_kg` minus `measured_contamination_kg`, and its `contamination_pct` is `measured_contamination_kg` divided by `input_gross_kg` and multiplied by 100, rounded half-up to two decimal places. The outcome forks on the partner's threshold. When `contamination_pct` is strictly below the partner's `contamination_reject_threshold_pct`, the batch closes as `CLOSED_ACCEPTED`: `finished_compost_kg` is `measured_net_kg` multiplied by the partner's `yield_ratio`, rounded half-up to two decimal places, `closed_at` is stamped, and every `ACCEPTED` drop whose site was served by a `COLLECTED` stop on the batch's route is reconciled — the drop is assigned this batch's id in `processing_batch_id`, receives a `final_net_kg`, and flips `credit_state` from `PROVISIONALLY_CREDITED` to `FINALLY_CREDITED`.

Final-net assignment distributes the batch's `measured_net_kg` across those drops proportionally to their `provisional_net_kg`, using largest-remainder rounding at 0.01 kg granularity so that the per-drop figures sum **exactly** to the batch's `measured_net_kg`. Each drop's raw share is the batch's `measured_net_kg` multiplied by the drop's `provisional_net_kg` and divided by the sum of `provisional_net_kg` across all included drops; each share is first floored to a whole 0.01-kg unit; the shortfall between `measured_net_kg` and the sum of the floored shares, expressed in whole 0.01-kg units and rounded to the nearest unit, is then distributed one 0.01-kg unit per drop in order of largest fractional remainder first, with ties broken by the drop's `occurred_at` (earliest first) and then its `created_at` (earliest first), until the shortfall is exhausted. If the included drops' provisional masses sum to zero, every included drop receives a `final_net_kg` of 0.

Reconciliation adjusts credits per drop. The delta is the difference of two independent roundings — the final net multiplied by `diversion_credit_rate`, rounded half-up to a whole credit, minus the provisional net multiplied by the same rate, likewise rounded — never the rounding of the raw difference. The participant's `bucket_credit_balance` is adjusted by that signed delta.

When `contamination_pct` is at or above the threshold, the batch instead closes as `CLOSED_REJECTED`: `finished_compost_kg` is 0, `closed_at` is stamped, and every drop linked to stops on the batch's route has its `verification_state` moved to `FLAGGED_CONTAMINATED` with a new `OPEN` `ContaminationReport` of severity `MAJOR`, its `drop_event_id` set, auto-created per drop; provisional credits are reversed. Batch listings support `status` filtering.

### 3.6. Compost Distribution and the Fair-Share Clamp

Finished compost flows back to participants through distributions. A `ProgramAdmin` opens a `CompostDistribution` over a `CLOSED_ACCEPTED` batch by supplying `batch_id`; the distribution starts `OPEN`, snapshots the batch's `finished_compost_kg` into `total_pool_kg` — an immutable snapshot that does not change as allocations are granted — stamps `opened_at` with the current logical clock, and starts `allocated_kg` at 0.

A `Participant` requests an allocation with `participant_id`, a `requested_kg`, a `credits_redeemed` spend, and — per §2.5 — `expected_distribution_version`. Each credit redeemed caps at most 1 kilogram of request. The request must be affordable: `credits_redeemed` no greater than the participant's `bucket_credit_balance`, and `requested_kg` greater than 0 — otherwise `ERR_INSUFFICIENT_BUCKET_CREDITS` (HTTP 409). A new allocation starts `REQUESTED` and increments the distribution's `version` by 1. Allocation listings support `participant_id` and `status` filters; distribution listings support `status` filtering.

Granting an allocation, a `ProgramAdmin` operation, requires the parent distribution to still be `OPEN` and applies the fair-share clamp to compute `allocation_kg`. The clamp takes the minimum of three caps, then bounds the result by the request itself. The **household-share cap** divides the pool remaining — `total_pool_kg` minus `allocated_kg` — in proportion to household size: the participant's `household_size` over the total `household_size` summed across all participants holding a `REQUESTED` or `DISTRIBUTED` allocation in this distribution, multiplied by the pool remaining. The **credit cap** is `credits_redeemed` kilograms flat. The **equal-split cap** is the pool remaining divided by the number of `REQUESTED` allocations including this one, so with several pending requests no large household can drain the pool ahead of smaller ones; with exactly one pending requester the equal-split cap equals the whole remaining pool and the binding constraint is the minimum of the request, the household share, and the credit cap. The granted `allocation_kg` is the minimum of `requested_kg` and those three caps, rounded half-up to two decimal places. If the total household weighting across `REQUESTED` and `DISTRIBUTED` allocations is zero — meaning no requests exist to weigh — the fair-share run fails with `ERR_DISTRIBUTION_NO_REQUESTS` (HTTP 409). The grant is also bounded pool-wide: if the distribution's `allocated_kg` plus the computed `allocation_kg` would exceed `total_pool_kg`, the grant fails with `ERR_DISTRIBUTION_POOL_EXHAUSTED` (HTTP 409).

A successful grant moves the allocation to `DISTRIBUTED`, debits `credits_redeemed` from the participant's `bucket_credit_balance`, adds the same amount to `bucket_credits_redeemed_total`, and adds `allocation_kg` to the distribution's `allocated_kg`. Cancelling a requested allocation — directly, or cascaded from cancelling the whole distribution — moves it to `CANCELLED` and refunds `credits_redeemed` to the participant's `bucket_credit_balance` without counting a redemption.

Closing a distribution requires that no `REQUESTED` allocations remain, failing with `ERR_DISTRIBUTION_HAS_PENDING_REQUESTS` (HTTP 409) otherwise, and moves it to `CLOSED`. Cancelling a distribution moves it to `CANCELLED` and cancels every `REQUESTED` allocation with the credit refund described above.

### 3.7. Complaints: Odor, Vector, and the SLA Clock

Neighbors reach the program through complaint tickets. An `Anonymous` caller files a complaint at a site with a free-form `reporter_contact`, a `kind` of `ODOR`, `VECTOR`, or `OTHER`, a `description`, and the `reported_at` moment the complaint was received. A new ticket starts `OPEN`; its `sla_due_at` is computed as `reported_at` plus 72 hours, and filing recomputes the site's posture — remember from §2.7 that unresolved complaints inside the rolling 14-day window count toward `WATCH`. Complaint listings support `status` and `kind` filters and are readable by `ProgramAdmin`, `SiteHost`, and `MunicipalAuditor`.

Acknowledging a ticket moves it from `OPEN` to `ACKNOWLEDGED` and stamps `acknowledged_at` with the current logical clock. Resolution is reachable from `OPEN`, `ACKNOWLEDGED`, or `REOPENED`; it moves the ticket to `RESOLVED`, stamps `resolved_at`, and recomputes the site's posture. A `MunicipalAuditor` may reopen a resolved ticket, but only twice over a ticket's lifetime: reopening requires `reopen_count` below 2, failing with `ERR_COMPLAINT_REOPEN_LIMIT` (HTTP 409) at the limit, and on success increments `reopen_count` by 1, clears `resolved_at`, moves the ticket to `REOPENED`, and recomputes posture.

Closure requires demonstrated stability: a ticket may move from `RESOLVED` to `CLOSED` only after it has remained `RESOLVED` through at least one full ops-run checkpoint — tracked by comparing the program's `ops_run_index` at resolve time against the current one — failing with `ERR_COMPLAINT_NOT_STABLE` (HTTP 409) if no ops run has intervened. `CLOSED` is terminal.

The ops-run checkpoint owns SLA bookkeeping: any ticket still unresolved when its `sla_due_at` passes has `sla_breached` set to true, and that flag is never cleared, even if the ticket is later resolved.

### 3.8. Diversion Reporting, Certification, and the Ops-Run Checkpoint

The municipality's tonnage figures are produced by `MunicipalAuditor` operators as `DiversionReport` records scoped to a program. Generating a report takes an inclusive `period_start`, an exclusive `period_end`, and a `method` selecting the calculation variant. The report starts `DRAFT` with all tonnage fields computed at generation time.

Both variants draw from drop events in the program whose `occurred_at` falls within the period window, and both compute `gross_diverted_kg` as the sum of `gross_weight_kg` and `contamination_kg` as the sum of `contamination_kg` over the included set. They diverge on inclusion and on net mass — deliberately, because the two variants answer different questions. The `PROVISIONAL_NET` variant is the fast, unaudited number: it includes drops whose `verification_state` is `PENDING_AUDIT`, `ACCEPTED`, or `FLAGGED_CONTAMINATED` — `REJECTED` drops are excluded — and sums each drop's `provisional_net_kg`. The `FINAL_NET` variant is the certified year-end figure: it includes only drops whose `credit_state` is `FINALLY_CREDITED` and sums each drop's batch-reconciled `final_net_kg`. The per-event rounding order is pinned: each event's net value is rounded half-up to two decimal places first, and the rounded per-event values are then summed into `net_diverted_kg`. Because partner-measured contamination tends to exceed participant-declared contamination, the final-net variant produces a smaller tonnage whenever reconciliation shrinks masses; the provisional variant correspondingly produces the larger figure. Finally, `diversion_rate_pct` is `net_diverted_kg` divided by `gross_diverted_kg` and multiplied by 100, rounded half-up to two decimal places — or exactly 0 when the gross is 0.

Certification enforces segregation of duties. Certifying a report moves it from `DRAFT` to `CERTIFIED` and requires the certifying auditor's `X-User-ID` to differ from the id that created the report — the creator's id is captured from the caller at report creation time — failing with `ERR_SOD_SAME_USER` (HTTP 403) on a self-certification; it also requires the report's `period_end` to be at or before the current logical clock, failing with `ERR_REPORT_PERIOD_NOT_CLOSED` (HTTP 409) for a period that has not yet closed. On certification, `certified_by` records the certifying auditor's `X-User-ID`. Certification also supersedes: when a new report with an identical period start, period end, and method is certified, any previously `CERTIFIED` report with that same period and method automatically transitions to `SUPERSEDED`. Diversion report listings support `status` and `method` filters and are restricted to `ProgramAdmin` and `MunicipalAuditor`.

The ops-run checkpoint is the program's periodic heartbeat, invoked by a `ProgramAdmin`, and it performs five duties in one pass: it increments the program's `ops_run_index` by 1; it flips every `ACTIVE` access grant whose `expires_at` has been reached to `EXPIRED`, auto-opening a `MINOR` contamination report on the grant's site when buckets are still checked out; it transitions every `ACTIVE` host agreement whose `term_end` has been reached to `EXPIRED`, clearing site links and dropping uncovered `OPERATIONAL` sites to posture `CLOSED`; it marks every complaint ticket still unresolved past its `sla_due_at` with `sla_breached` set to true; it expires bucket credits granted more than 365 days earlier, consuming oldest-first per §2.8; and it recomputes every site's posture from scratch.

The program-level totals tell the same story at aggregate: `total_diverted_kg` is the sum of `final_net_kg` across all of the program's confirmed drop events, and `total_contamination_kg` is the sum of `contamination_kg` across those same confirmed drops.

## 4. Endpoint Definitions

All endpoints are mounted at the API root. Creating a new resource returns HTTP 201 with the created resource; state transitions, modifications, and reads return HTTP 200. List endpoints follow §2.3 pagination. Request bodies, preconditions, and side effects are defined by the workflows in §3; the table below is the structural index only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Advance the logical clock to `to_iso8601`; returns `now` | ProgramAdmin |
| POST | `/programs` | Create a program | ProgramAdmin |
| GET | `/programs/{id}` | Get a program | ProgramAdmin, SiteHost, Participant, RouteOperator, ProcessingPartner, MunicipalAuditor |
| POST | `/programs/{id}/activate` | Activate (or re-activate) a program | ProgramAdmin |
| POST | `/programs/{id}/suspend` | Suspend a program; all site postures forced SUSPENDED | ProgramAdmin |
| POST | `/programs/{id}/close` | Close a program | ProgramAdmin |
| POST | `/programs/{id}/run_ops` | Ops-run checkpoint: expire grants/agreements/credits, mark SLA breaches, recompute postures | ProgramAdmin |
| POST | `/programs/{id}/sites` | Create a site | ProgramAdmin |
| GET | `/programs/{id}/sites` | List sites (archived excluded by default) | ProgramAdmin, SiteHost, Participant, RouteOperator, ProcessingPartner, MunicipalAuditor |
| GET | `/programs/{id}/sites/{siteId}` | Get a site | ProgramAdmin, SiteHost, Participant, RouteOperator, ProcessingPartner, MunicipalAuditor |
| POST | `/programs/{id}/sites/{siteId}/commission` | Commission a site (requires ACTIVE host agreement) | ProgramAdmin |
| POST | `/programs/{id}/sites/{siteId}/decommission` | Decommission a site | ProgramAdmin |
| POST | `/programs/{id}/sites/{siteId}/archive` | Soft-delete a decommissioned site | ProgramAdmin |
| POST | `/programs/{id}/host-agreements` | Create a host agreement | ProgramAdmin |
| GET | `/programs/{id}/host-agreements` | List host agreements | ProgramAdmin, SiteHost, MunicipalAuditor |
| GET | `/programs/{id}/host-agreements/{agreementId}` | Get a host agreement | ProgramAdmin, SiteHost, MunicipalAuditor |
| POST | `/programs/{id}/host-agreements/{agreementId}/activate` | Activate an agreement | ProgramAdmin |
| POST | `/programs/{id}/host-agreements/{agreementId}/breach-notice` | Issue breach notice | ProgramAdmin |
| POST | `/programs/{id}/host-agreements/{agreementId}/cure` | Cure a breach | ProgramAdmin |
| POST | `/programs/{id}/host-agreements/{agreementId}/terminate` | Terminate an agreement | ProgramAdmin |
| POST | `/programs/{id}/materials` | Create a material category | ProgramAdmin |
| GET | `/programs/{id}/materials` | List material categories | ProgramAdmin, SiteHost, Participant, RouteOperator, ProcessingPartner, MunicipalAuditor |
| PATCH | `/programs/{id}/materials/{materialId}` | Update `active` flag or `description` | ProgramAdmin |
| POST | `/programs/{id}/participants/register` | Register a participant | Anonymous |
| GET | `/programs/{id}/participants` | List participants | ProgramAdmin, MunicipalAuditor |
| GET | `/programs/{id}/participants/{participantId}` | Get a participant | ProgramAdmin, Participant, MunicipalAuditor |
| POST | `/programs/{id}/participants/{participantId}/verify` | Verify registration with `verification_token` | Anonymous |
| POST | `/programs/{id}/participants/{participantId}/suspend` | Suspend a participant (3rd suspension deactivates; grants revoked) | ProgramAdmin |
| POST | `/programs/{id}/participants/{participantId}/reinstate` | Reinstate a suspended participant | ProgramAdmin |
| POST | `/programs/{id}/participants/{participantId}/deactivate` | Deactivate a participant; credits expired; grants revoked | ProgramAdmin |
| POST | `/programs/{id}/participants/{participantId}/grants` | Issue an access grant for a site | ProgramAdmin |
| GET | `/programs/{id}/participants/{participantId}/grants` | List a participant's grants | ProgramAdmin, Participant, MunicipalAuditor |
| POST | `/programs/{id}/participants/{participantId}/grants/{grantId}/revoke` | Revoke a grant | ProgramAdmin |
| POST | `/programs/{id}/sites/{siteId}/drops` | Record a drop (OCC on the site's version) | Participant |
| GET | `/programs/{id}/sites/{siteId}/drops` | List drops at a site | ProgramAdmin, SiteHost, Participant, MunicipalAuditor |
| GET | `/programs/{id}/sites/{siteId}/drops/{dropId}` | Get a drop | ProgramAdmin, SiteHost, Participant, MunicipalAuditor |
| POST | `/programs/{id}/sites/{siteId}/drops/{dropId}/accept` | Accept a pending drop | SiteHost |
| POST | `/programs/{id}/sites/{siteId}/drops/{dropId}/reject` | Reject a flagged drop | SiteHost |
| POST | `/programs/{id}/sites/{siteId}/contamination-reports` | Open a contamination report | MunicipalAuditor |
| GET | `/programs/{id}/sites/{siteId}/contamination-reports` | List contamination reports | ProgramAdmin, SiteHost, MunicipalAuditor |
| POST | `/programs/{id}/sites/{siteId}/contamination-reports/{reportId}/send-feedback` | Send participant feedback | ProgramAdmin |
| POST | `/programs/{id}/sites/{siteId}/contamination-reports/{reportId}/resolve` | Resolve a report | ProgramAdmin |
| POST | `/programs/{id}/sites/{siteId}/contamination-reports/{reportId}/dismiss` | Dismiss a report | MunicipalAuditor |
| POST | `/programs/{id}/partners` | Register a processing partner | ProgramAdmin |
| GET | `/programs/{id}/partners` | List partners | ProgramAdmin, RouteOperator, ProcessingPartner, MunicipalAuditor |
| POST | `/programs/{id}/routes` | Plan a collection route | RouteOperator |
| GET | `/programs/{id}/routes` | List routes | ProgramAdmin, RouteOperator, ProcessingPartner, MunicipalAuditor |
| GET | `/programs/{id}/routes/{routeId}` | Get a route | ProgramAdmin, RouteOperator, ProcessingPartner, MunicipalAuditor |
| POST | `/programs/{id}/routes/{routeId}/dispatch` | Dispatch a route | RouteOperator |
| POST | `/programs/{id}/routes/{routeId}/complete` | Complete a route; opens a processing batch at the partner | RouteOperator |
| POST | `/programs/{id}/routes/{routeId}/cancel` | Cancel a planned route | RouteOperator |
| POST | `/programs/{id}/routes/{routeId}/stops` | Add a stop to a route (OCC on the route's version) | RouteOperator |
| GET | `/programs/{id}/routes/{routeId}/stops` | List stops of a route | ProgramAdmin, RouteOperator, ProcessingPartner, MunicipalAuditor |
| POST | `/programs/{id}/routes/{routeId}/stops/{stopId}/collect` | Mark a stop collected with `actual_pickup_kg` | RouteOperator |
| POST | `/programs/{id}/routes/{routeId}/stops/{stopId}/skip` | Skip a stop | RouteOperator |
| POST | `/programs/{id}/routes/{routeId}/stops/{stopId}/cancel` | Cancel a stop on a planned route | RouteOperator |
| GET | `/programs/{id}/partners/{partnerId}/batches` | List batches at a partner | ProgramAdmin, ProcessingPartner, MunicipalAuditor |
| GET | `/programs/{id}/partners/{partnerId}/batches/{batchId}` | Get a batch | ProgramAdmin, ProcessingPartner, MunicipalAuditor |
| POST | `/programs/{id}/partners/{partnerId}/batches/{batchId}/close` | Close a batch with partner-measured contamination | ProcessingPartner |
| POST | `/programs/{id}/distributions` | Open a compost distribution over a CLOSED_ACCEPTED batch | ProgramAdmin |
| GET | `/programs/{id}/distributions` | List distributions | ProgramAdmin, Participant, MunicipalAuditor |
| GET | `/programs/{id}/distributions/{distributionId}` | Get a distribution | ProgramAdmin, Participant, MunicipalAuditor |
| POST | `/programs/{id}/distributions/{distributionId}/allocations` | Request an allocation (OCC on the distribution's version) | Participant |
| GET | `/programs/{id}/distributions/{distributionId}/allocations` | List allocations of a distribution | ProgramAdmin, Participant, MunicipalAuditor |
| POST | `/programs/{id}/distributions/{distributionId}/allocations/{allocationId}/distribute` | Grant an allocation after the fair-share clamp | ProgramAdmin |
| POST | `/programs/{id}/distributions/{distributionId}/allocations/{allocationId}/cancel` | Cancel a requested allocation | ProgramAdmin |
| POST | `/programs/{id}/distributions/{distributionId}/close` | Close a distribution | ProgramAdmin |
| POST | `/programs/{id}/distributions/{distributionId}/cancel` | Cancel a distribution; pending allocations refunded | ProgramAdmin |
| POST | `/programs/{id}/sites/{siteId}/complaints` | File an odor/vector complaint | Anonymous |
| GET | `/programs/{id}/sites/{siteId}/complaints` | List complaints at a site | ProgramAdmin, SiteHost, MunicipalAuditor |
| POST | `/programs/{id}/sites/{siteId}/complaints/{complaintId}/acknowledge` | Acknowledge a complaint | ProgramAdmin |
| POST | `/programs/{id}/sites/{siteId}/complaints/{complaintId}/resolve` | Resolve a complaint | ProgramAdmin |
| POST | `/programs/{id}/sites/{siteId}/complaints/{complaintId}/reopen` | Reopen a resolved complaint | MunicipalAuditor |
| POST | `/programs/{id}/sites/{siteId}/complaints/{complaintId}/close` | Close a resolved complaint after one stable ops run | ProgramAdmin |
| GET | `/sites` | List sites with optional foreign-key filters | ProgramAdmin, SiteHost, Participant, RouteOperator, ProcessingPartner, MunicipalAuditor |
| GET | `/host-agreements` | List host agreements with optional foreign-key filters | ProgramAdmin, SiteHost, MunicipalAuditor |
| GET | `/materials` | List material categories with optional foreign-key filters | ProgramAdmin, SiteHost, Participant, RouteOperator, ProcessingPartner, MunicipalAuditor |
| GET | `/participants` | List participants with optional foreign-key filters | ProgramAdmin, MunicipalAuditor |
| GET | `/grants` | List access grants with optional foreign-key filters | ProgramAdmin, Participant, MunicipalAuditor |
| GET | `/drops` | List drop events with optional foreign-key filters | ProgramAdmin, SiteHost, Participant, MunicipalAuditor |
| GET | `/contamination-reports` | List contamination reports with optional foreign-key filters | ProgramAdmin, SiteHost, MunicipalAuditor |
| GET | `/routes` | List collection routes with optional foreign-key filters | ProgramAdmin, RouteOperator, ProcessingPartner, MunicipalAuditor |
| GET | `/stops` | List route stops with optional foreign-key filters | ProgramAdmin, RouteOperator, ProcessingPartner, MunicipalAuditor |
| GET | `/partners` | List processing partners with optional foreign-key filters | ProgramAdmin, RouteOperator, ProcessingPartner, MunicipalAuditor |
| GET | `/batches` | List processing batches with optional foreign-key filters | ProgramAdmin, ProcessingPartner, MunicipalAuditor |
| GET | `/distributions` | List distributions with optional foreign-key filters | ProgramAdmin, Participant, MunicipalAuditor |
| GET | `/allocations` | List allocations with optional foreign-key filters | ProgramAdmin, Participant, MunicipalAuditor |
| GET | `/complaints` | List complaint tickets with optional foreign-key filters | ProgramAdmin, SiteHost, MunicipalAuditor |
| GET | `/diversion-reports` | List diversion reports with optional foreign-key filters | ProgramAdmin, MunicipalAuditor |
| GET | `/sites/{siteId}` | Get a site by id (flat alias) | ProgramAdmin, SiteHost, Participant, RouteOperator, ProcessingPartner, MunicipalAuditor |
| GET | `/host-agreements/{agreementId}` | Get a host agreement by id (flat alias) | ProgramAdmin, SiteHost, MunicipalAuditor |
| GET | `/materials/{materialId}` | Get a material category by id (flat alias) | ProgramAdmin, SiteHost, Participant, RouteOperator, ProcessingPartner, MunicipalAuditor |
| GET | `/participants/{participantId}` | Get a participant by id (flat alias) | ProgramAdmin, Participant, MunicipalAuditor |
| GET | `/grants/{grantId}` | Get an access grant by id (flat alias) | ProgramAdmin, Participant, MunicipalAuditor |
| GET | `/drops/{dropId}` | Get a drop event by id (flat alias) | ProgramAdmin, SiteHost, Participant, MunicipalAuditor |
| GET | `/contamination-reports/{reportId}` | Get a contamination report by id (flat alias) | ProgramAdmin, SiteHost, MunicipalAuditor |
| GET | `/routes/{routeId}` | Get a route by id (flat alias) | ProgramAdmin, RouteOperator, ProcessingPartner, MunicipalAuditor |
| GET | `/stops/{stopId}` | Get a route stop by id (flat alias) | ProgramAdmin, RouteOperator, ProcessingPartner, MunicipalAuditor |
| GET | `/partners/{partnerId}` | Get a processing partner by id (flat alias) | ProgramAdmin, RouteOperator, ProcessingPartner, MunicipalAuditor |
| GET | `/batches/{batchId}` | Get a processing batch by id (flat alias) | ProgramAdmin, ProcessingPartner, MunicipalAuditor |
| GET | `/distributions/{distributionId}` | Get a distribution by id (flat alias) | ProgramAdmin, Participant, MunicipalAuditor |
| GET | `/allocations/{allocationId}` | Get an allocation by id (flat alias) | ProgramAdmin, Participant, MunicipalAuditor |
| GET | `/complaints/{complaintId}` | Get a complaint ticket by id (flat alias) | ProgramAdmin, SiteHost, MunicipalAuditor |
| POST | `/programs/{id}/diversion-reports` | Generate a diversion report for a period (method selects variant) | MunicipalAuditor |
| GET | `/programs/{id}/diversion-reports` | List diversion reports | ProgramAdmin, MunicipalAuditor |
| GET | `/programs/{id}/diversion-reports/{reportId}` | Get a diversion report | ProgramAdmin, MunicipalAuditor |
| GET | `/diversion-reports/{reportId}` | Get a diversion report by id (flat alias) | ProgramAdmin, MunicipalAuditor |
| POST | `/programs/{id}/diversion-reports/{reportId}/certify` | Certify a report (certifier must differ from creator) | MunicipalAuditor |

The flat collection listings accept the same `limit` and `offset` parameters as nested listings, plus optional foreign-key filters matching the resource's parent fields — for example `program_id`, `site_id`, `participant_id`, `route_id`, `partner_id`, `batch_id`, `distribution_id`, `access_grant_id`, `material_category_id`, `processing_batch_id`, `host_agreement_id`, and `drop_event_id` where applicable — together with the resource's own enum filters such as `status`, `verification_state`, `credit_state`, `severity`, `kind`, `active`, `method`, and `include_archived` where supported.

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows in §2 and §3; this table is the index of identifiers and statuses only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_PROGRAM_NO_OPERATIONAL_SITE | 409 |
| ERR_PROGRAM_NO_MATERIAL_CATEGORY | 409 |
| ERR_PROGRAM_HAS_OPERATIONAL_SITES | 409 |
| ERR_SITE_NO_ACTIVE_AGREEMENT | 409 |
| ERR_SITE_NOT_EMPTY | 409 |
| ERR_SITE_HAS_SCHEDULED_PICKUPS | 409 |
| ERR_SITE_HAS_ACTIVE_GRANTS | 409 |
| ERR_INVALID_TERM | 409 |
| ERR_AGREEMENT_OVERLAP | 409 |
| ERR_AGREEMENT_ALREADY_EXPIRED | 409 |
| ERR_CURE_PERIOD_ELAPSED | 409 |
| ERR_CURE_PERIOD_NOT_ELAPSED | 409 |
| ERR_INVALID_VERIFICATION_TOKEN | 400 |
| ERR_PARTICIPANT_PERMANENTLY_DEACTIVATED | 409 |
| ERR_PARTICIPANT_HAS_PENDING_ALLOCATIONS | 409 |
| ERR_BUCKETS_STILL_OUT | 409 |
| ERR_SITE_POSTURE_BLOCKS_DROP | 409 |
| ERR_MATERIAL_NOT_ACCEPTED | 409 |
| ERR_ACCESS_GRANT_INVALID | 409 |
| ERR_DROP_OUTSIDE_AGREEMENT_TERM | 409 |
| ERR_FEEDBACK_REQUIRES_DROP_LINK | 409 |
| ERR_ROUTE_HAS_NO_STOPS | 409 |
| ERR_ROUTE_OVER_CAPACITY | 409 |
| ERR_PARTNER_INACTIVE | 409 |
| ERR_PARTNER_DOUBLE_BOOKED | 409 |
| ERR_ROUTE_NOT_DISPATCHED | 409 |
| ERR_ROUTE_NOT_PLANNED | 409 |
| ERR_ROUTE_STOPS_PENDING | 409 |
| ERR_PICKUP_EXCEEDS_AVAILABLE | 409 |
| ERR_DISTRIBUTION_HAS_PENDING_REQUESTS | 409 |
| ERR_DISTRIBUTION_POOL_EXHAUSTED | 409 |
| ERR_DISTRIBUTION_NO_REQUESTS | 409 |
| ERR_INSUFFICIENT_BUCKET_CREDITS | 409 |
| ERR_COMPLAINT_REOPEN_LIMIT | 409 |
| ERR_COMPLAINT_NOT_STABLE | 409 |
| ERR_SOD_SAME_USER | 403 |
| ERR_REPORT_PERIOD_NOT_CLOSED | 409 |

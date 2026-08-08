# Noise-Ordinance & Nuisance Complaint API — Product Requirements Document

## 1. Introduction

Municipalities receive a steady stream of noise complaints — late-night amplified music, early-morning construction, idling machinery, barking animals — and enforcing the local ordinance fairly requires a chain of judgment calls: was the reported level actually above the limit that applied at that hour, was a construction or event variance in force that legalized the noise, and does this parcel have a pattern of substantiated violations serious enough to warrant chronic-nuisance designation and abatement. This API is the system of record for that entire chain. It governs complaint intake, field decibel inspection, substantiation into a warning or fined citation, escalating fines for repeat offenders, variance-permit issuance, cross-agency referral, appeal hearings, and the abatement lifecycle for chronically offending properties.

The platform is built around a few hard commitments. Every enforcement action carries an auditable money ledger where balances are derived, never stored ad hoc. Chronic-nuisance posture and abatement posture evolve as two independent axes on the same parcel. Appeal hearings enforce segregation of duties so that the officer who issued a citation can never sit in judgment of it. Because several actors read and write the same parcels and citations, selected mutations are guarded by optimistic concurrency control to prevent a client from acting on a stale reading. A server-driven logical clock makes all time-dependent behavior — daytime versus nighttime limits, payment due dates, late penalties, and abatement deadlines — fully deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope conventions, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly five roles: `CodeOfficer`, `HearingOfficer`, `PermitClerk`, `Resident`, and `SystemAdmin`. A `CodeOfficer` reviews, inspects, substantiates, and dismisses complaints, issues enforcements, opens manual abatement orders, and routes cross-agency referrals. A `HearingOfficer` schedules and decides appeal hearings. A `PermitClerk` processes variance permits — application, issuance, denial, and revocation. A `Resident` is a member of the public who files complaints, applies for variances, contests citations, and records payments. A `SystemAdmin` configures noise-limit policies and drives the logical clock.

For all five roles, `X-User-ID` is an **opaque operator identifier** that is not tied to any persisted entity; the server never resolves it to a stored record or compares it to any resource's `id`. The server does, however, record the acting user's identifier where the workflow calls for it: the `CodeOfficer` who records a field reading is captured as `inspected_by_user_id` on the resulting inspection, the `CodeOfficer` who substantiates a complaint is captured as `issued_by_user_id` on the resulting enforcement, and the presiding officer supplied when a hearing is scheduled is captured as `hearing_officer_id`. These recorded identifiers drive the segregation-of-duties rule described in §3.6; they are never used for ownership lookups.

Any read (`GET`) endpoint is available to all five roles. Write endpoints are restricted as enumerated in §4.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object.

### 2.4. Common Resource Properties and Append-Only Records

Most resources — `Property`, `NoiseLimitPolicy`, `VariancePermit`, `Complaint`, `Enforcement`, `Hearing`, `AbatementOrder`, and `CrossAgencyReferral` — carry the full set of system-managed fields: an `id` (a server-minted UUID with no type prefix), a `created_at` and an `updated_at` timestamp (both ISO 8601 UTC with three fractional digits), and an integer `version` that starts at its initial value on creation and increments by one on every mutation. The `updated_at` field is refreshed on every mutation.

Two resources are **append-only records** and therefore carry only `id` and `created_at` — they have neither `updated_at` nor `version`, because they are never mutated after they are written. The first is `Inspection`, an immutable field reading. The second is `Payment`, an immutable ledger row; the ledger has no void path, so a reversal is always recorded as a new row rather than by editing an existing one.

### 2.5. Validation Order and Nested-Resource Resolution

When a request could fail more than one check, the checks are evaluated in a fixed priority order, and the first failure is the one reported:

1. **Authentication** — headers present and role known, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role may perform this operation, else `ERR_UNAUTHORIZED` (403).
3. **Existence** — every id in the path is resolved left to right, and any foreign-key id in the body is resolved, else the corresponding not-found error at HTTP 404: `ERR_PROPERTY_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, `ERR_VARIANCE_NOT_FOUND`, `ERR_ENFORCEMENT_NOT_FOUND`, `ERR_HEARING_NOT_FOUND`, `ERR_ABATEMENT_NOT_FOUND`, or `ERR_REFERRAL_NOT_FOUND`. For a nested path, the leftmost identifier that fails to resolve determines which not-found error is returned before any deeper identifier is examined.
4. **Body well-formedness** — required fields present and correctly typed (`ERR_VALIDATION`), enum fields within their declared set (`ERR_INVALID_ENUM`), and any supplied time window having its end strictly after its start (`ERR_INVALID_WINDOW`), all at HTTP 400.
5. **State** — the target resource is in the correct state for the operation (409-class state errors listed in §5); where no more specific state error applies, the generic `ERR_INVALID_STATE` (409) is returned.
6. **Optimistic concurrency** — where an endpoint requires an expected-version field, it must match the parent's current `version`, else `ERR_STALE_VERSION` (412).
7. **Referential** — cross-entity linkage holds, e.g. a policy is configured for the property's zoning, or a manual abatement's enforcement belongs to the named property (409-class referential errors).
8. **Temporal / interval** — variance-coverage, variance-window-overlap, hearing-slot-buffer, and abatement-deadline rules (409-class temporal errors).
9. **Segregation of duties** — the hearing decider differs from the citation issuer, else `ERR_SEGREGATION_OF_DUTIES` (403).
10. **Domain thresholds** — substantiation evidence, variance decibel cap, and reduction-fraction range (422-class errors).
11. **Fiscal** — a payment may not exceed the outstanding balance, else `ERR_PAYMENT_EXCEEDS_OUTSTANDING` (402).

This ordering is contractual. For example, at hearing decision time the segregation-of-duties check (step 9) is evaluated before the reduction-fraction range check (step 10), so a decision submitted by the issuing officer with an out-of-range `reduction_pct` fails with `ERR_SEGREGATION_OF_DUTIES`, not `ERR_REDUCTION_PCT_INVALID`.

### 2.6. The Logical Clock

All time-dependent behavior reads a server-managed **logical clock** rather than wall-clock time. At startup the clock reads exactly `2026-05-01T00:00:00Z` and never falls back to wall-clock; before any client sets it, that default is the current instant. A `SystemAdmin` may advance or set the clock by supplying a target instant in the `to_iso8601` field. Every subsequent computation that depends on "now" — an enforcement's `issued_at` and `due_date`, a hearing's `decided_at`, accrued late penalties, and the abatement-deadline comparison — uses the clock's current value.

### 2.7. Monetary Precision and Rounding

All money is handled in integer **cents**; fields ending in `_cents` are whole-cent integers. Wherever a calculation produces a fractional cent, it is rounded half up to the nearest whole cent. Fine escalation, reduction of a fine after a hearing, per-day late penalties, and variance fees all follow this rule. Decibel values are exact and are never rounded.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control because they race against background cascades that legitimately advance a parent's `version`.

Recording a payment against a citation requires the request to carry `expected_enforcement_version`, holding the `version` of the target `Enforcement` that the client last observed. If that value does not match the enforcement's current `version` — because, since the client read the fine, a hearing outcome or a prior payment changed `effective_fine_cents` or the outstanding balance and bumped the enforcement's `version` — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Partial payments are expected to succeed in sequence, so this guard is what prevents a client from paying against a fine amount it never actually saw.

Opening a **manual** abatement order requires the request to carry `expected_property_version`, holding the `version` of the target `Property` that the client last observed. If a substantiate or dismiss cascade has since changed the property's `chronic_status` or `substantiated_violation_count` and bumped its `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), since the operator's basis for opening the order is stale. Endpoints other than these two do not accept a version field and are not subject to this check.

### 2.9. Cascading State Consistency

Several operations mutate more than one resource in a single atomic step, and each cascade is part of the operation's contract. Substantiating a complaint creates an enforcement, then increments the property's substantiated-violation tally and recomputes its chronic posture, and — only if that recompute reaches designation — creates an abatement order and flips the abatement posture. A hearing dismissal reverses that chain: it dismisses the citation, may issue a refund, decrements the tally, recomputes the posture, and may vacate a previously auto-created abatement order. Whenever such a cascade mutates a resource that carries a `version`, that resource's `version` is incremented and its `updated_at` refreshed. Where a single operation touches both an enforcement and its property, both counters advance independently. The specific triggers, ordering, and side effects are described in the workflow narratives of §3.

## 3. Business Logic & Workflows

### 3.1. Parcels and Noise-Limit Policies

The parcel is the anchor of the system. A `CodeOfficer` or a `SystemAdmin` registers a `Property` by supplying its street `address` and its `zoning_type`, which must be one of `RESIDENTIAL`, `COMMERCIAL`, `INDUSTRIAL`, or `MIXED`. On registration the parcel's derived posture is initialized: `substantiated_violation_count` is 0, `chronic_status` is `NONE`, and `abatement_status` is `NONE`. Parcels can be listed — optionally narrowed by `zoning_type` or by `chronic_status` — and fetched individually to inspect their posture and counts.

Noise limits are configured per zoning by a `SystemAdmin`. A `NoiseLimitPolicy` names the `zoning_type` it governs and sets a `day_limit_db` and a `night_limit_db` together with the two hour boundaries `day_start_hour` and `night_start_hour`, each an integer UTC hour from 0 through 23. The daytime window is half-open: it runs from `day_start_hour` inclusive up to `night_start_hour` exclusive, and any hour outside that window is nighttime. At most one policy may exist per zoning; an attempt to configure a second policy for a zoning already covered is rejected with `ERR_DUPLICATE_POLICY`. Policies may be listed, optionally filtered by `zoning_type`.

### 3.2. Filing and Reviewing Complaints

A `Resident` or a `CodeOfficer` files a `Complaint` against a parcel. The payload carries the `property_id`, the `reported_at` instant at which the noise occurred (which later selects the applicable day/night limit and any covering variance window), and a `noise_type` drawn from `CONSTRUCTION`, `AMPLIFIED_MUSIC`, `MACHINERY`, `ANIMAL`, `VEHICLE`, or `OTHER`. Three optional inputs round out intake: a `reported_decibel` the complainant estimated (advisory only — substantiation never relies on it), a `source` channel of `PHONE`, `ONLINE`, or `OFFICER` that defaults to `PHONE`, and an optional `complainant_contact` string. A freshly filed complaint begins in `RECEIVED`.

A `CodeOfficer` opens a complaint for review, advancing it `RECEIVED → UNDER_REVIEW`. From `UNDER_REVIEW` the complaint can only reach the two terminal outcomes `SUBSTANTIATED` or `DISMISSED`. Dismissing an under-review complaint moves it `UNDER_REVIEW → DISMISSED`; an optional `reason` may accompany the dismissal, and no further side effects occur. Substantiation and dismissal both require the complaint to be in `UNDER_REVIEW`; attempting either from any other state is rejected with `ERR_COMPLAINT_NOT_UNDER_REVIEW`. Complaints may be listed, optionally filtered by `property_id` or `status`.

### 3.3. Field Inspections and the Effective Limit

Before a complaint can be substantiated, a `CodeOfficer` must record at least one field decibel reading against it. Recording an `Inspection` supplies a `measured_decibel` and the `measured_at` instant of the reading; the complaint under inspection supplies the `complaint_id` linkage. Two values are then derived and frozen onto the reading, and the acting officer is stamped onto `inspected_by_user_id`.

The first derived value is `effective_limit_db`. The system locates the single `NoiseLimitPolicy` whose `zoning_type` equals the parcel's `zoning_type`; if no policy is configured for that zoning, the reading cannot be recorded and the request is rejected with `ERR_POLICY_NOT_CONFIGURED`. It then takes the UTC hour-of-day of `measured_at`: when that hour is at least `day_start_hour` and strictly less than `night_start_hour`, `effective_limit_db` is the policy's `day_limit_db`; otherwise it is the `night_limit_db`. The second derived value is the boolean `exceeds_limit`, which is true if and only if `measured_decibel` is strictly greater than `effective_limit_db`. A reading exactly equal to the limit is **not** a violation. Readings for a complaint may be listed in the order they were recorded.

### 3.4. Substantiation, Enforcement, and Fine Escalation

A `CodeOfficer` substantiates an under-review complaint, which — when all preconditions hold — issues an `Enforcement` and cascades posture changes onto the parcel. Three domain preconditions gate substantiation beyond the `UNDER_REVIEW` state requirement. There must be at least one inspection on record for the complaint, else `ERR_NO_INSPECTION_ON_RECORD`. The latest such inspection must have exceeded the limit — its `measured_decibel` strictly above its `effective_limit_db` — else `ERR_NOISE_WITHIN_LIMIT`. And no `ISSUED` variance on the parcel may legalize the event: if some issued variance's approved window covers the complaint's `reported_at` and grants a `permitted_max_db` at least as high as the latest inspection's `measured_decibel`, substantiation is blocked with `ERR_VARIANCE_COVERS_COMPLAINT`.

When substantiation proceeds, the complaint moves `UNDER_REVIEW → SUBSTANTIATED` and the following cascade runs. **First**, a new enforcement is created carrying the `complaint_id` and the parcel's `property_id` (denormalized for escalation scoping). Its `escalation_level` is computed as the number of non-dismissed enforcements — those whose `status` is anything other than `DISMISSED` — already on this parcel whose `issued_at` falls within the rolling window of the last 365 days, counted immediately before this new one. Its `tier`, `assessed_fine_cents`, and initial `effective_fine_cents` follow the escalation rule below. The acting officer is stamped onto `issued_by_user_id`, `issued_at` is set to the logical clock, and `due_date` is set to 30 days after `issued_at`. The enforcement begins in `ISSUED`.

The escalation rule determines tier and fine together. If `escalation_level` is 0 — the parcel's first non-dismissed enforcement in the window — the `tier` is `WARNING` and `assessed_fine_cents` is 0; a warning carries no fine and, as noted in §3.6, cannot be appealed. Otherwise the `tier` is `CITATION` and the fine is a three-factor product. The base fine is $100.00 (10000 cents). A chronic factor of 1.5 applies when the parcel's `chronic_status` is `DESIGNATED` as it stands **before** this substantiation's chronic recompute, and is 1.0 otherwise. A zoning factor scales the fine by zoning: 1.0 for `RESIDENTIAL`, 1.5 for `COMMERCIAL`, 0.75 for `INDUSTRIAL`, and 1.25 for `MIXED`. The raw fine is the base multiplied by `escalation_level`, then by the zoning factor, then by the chronic factor; it is rounded half up to whole cents and then capped so that `assessed_fine_cents` never exceeds $5,000.00 (500000 cents). At issuance `effective_fine_cents` equals `assessed_fine_cents`.

**Second**, the parcel's `substantiated_violation_count` is increased by one and its `chronic_status` is recomputed. The recompute counts the parcel's non-dismissed enforcements within the same 365-day rolling window and sets the count into `substantiated_violation_count`: a count of 3 or more yields `DESIGNATED`, a count of 2 (below 3) yields `WATCH`, and anything below 2 yields `NONE`. **Third**, if and only if this recompute newly reaches `DESIGNATED`, an `AbatementOrder` is auto-created for the parcel with `trigger_source` `CHRONIC_DESIGNATION` and `status` `PENDING`, and the parcel's `abatement_status` moves to `UNDER_ABATEMENT`. The parcel's `version` is incremented by the cascade.

The parcel tracks two independent axes. The `chronic_status` axis moves `NONE → WATCH → DESIGNATED` as substantiations accumulate and back down (`DESIGNATED → WATCH → NONE`) as dismissals reduce the count. The `abatement_status` axis — `NONE`, `UNDER_ABATEMENT`, `ABATED` — is driven separately by the abatement-order lifecycle. The two axes evolve independently.

### 3.5. Variance Permits

A `Resident` or a `PermitClerk` applies for a `VariancePermit` covering a parcel identified by `property_id`. The application declares a `permit_type` of `CONSTRUCTION` or `EVENT`, a requested window given by `requested_start` and `requested_end` (the end must be strictly after the start, else `ERR_INVALID_WINDOW`), the `permitted_max_db` ceiling the applicant seeks, and, for events, an `expected_attendees` headcount that defaults to 0. A new application begins in `UNDER_REVIEW`, and at creation a provisional `fee_estimate_cents` is computed from the **requested** window and attendees.

The fee formula depends on type. For a `CONSTRUCTION` permit the fee is a base of $50.00 (5000 cents) plus $25.00 (2500 cents) per day of the window, where the number of days is the window's total duration in seconds divided by 86,400 and rounded **up** to the next whole day. For an `EVENT` permit the fee is a base of $100.00 (10000 cents) plus $0.50 (50 cents) per expected attendee. The estimate uses the requested window and requested attendees; the final fee, computed at issuance, uses the approved window and approved attendees, so the two diverge whenever the clerk narrows the window.

A `PermitClerk` issues, denies, or revokes a permit. Issuing moves it `UNDER_REVIEW → ISSUED`. At issuance the clerk may narrow the window by supplying `approved_start` and `approved_end` (and may adjust `permitted_max_db`); if omitted, the approved window defaults to the requested window. The approved window is then locked, and `fee_final_cents` is computed from it. Three checks gate issuance: the approved window must be valid with `approved_end` strictly after `approved_start` (`ERR_INVALID_WINDOW`); the `permitted_max_db` must not exceed the absolute ceiling of 95 decibels (`ERR_VARIANCE_DB_EXCEEDS_CAP`); and the new approved window, treated as the half-open interval from `approved_start` inclusive to `approved_end` exclusive, must not overlap the approved window of any other `ISSUED` variance on the same parcel (`ERR_VARIANCE_WINDOW_OVERLAP`). Issuing, denying, or revoking are state-gated: issue and deny require the permit to be `UNDER_REVIEW`, else `ERR_VARIANCE_NOT_UNDER_REVIEW`; revoke requires it to be `ISSUED`, else `ERR_VARIANCE_NOT_ISSUED`. Denial moves the permit `UNDER_REVIEW → DENIED` and revocation moves it `ISSUED → REVOKED`; each accepts an optional `reason`. Variances may be listed, optionally filtered by `property_id`, `status`, or `permit_type`.

### 3.6. Contesting Citations: Hearings and Appeals

Only a fined citation may be appealed. A `Resident` contests an enforcement, moving it `ISSUED → CONTESTED`; this requires the enforcement's `tier` to be `CITATION`, and contesting a `WARNING` is rejected with `ERR_ENFORCEMENT_NOT_CITATION`. Contesting increments the enforcement's `version`.

A `HearingOfficer` then schedules an appeal hearing on a contested citation, moving it `CONTESTED → HEARING_SCHEDULED` and creating a `Hearing` in `PENDING`. Scheduling a hearing on an enforcement that is not `CONTESTED` is rejected with `ERR_ENFORCEMENT_NOT_CONTESTED`. The request supplies the `scheduled_at` start instant, the presiding `hearing_officer_id`, and an optional `duration_minutes` slot length that defaults to 30; the slot occupies the closed interval from `scheduled_at` to `scheduled_at` plus `duration_minutes`. A per-officer buffer protects the docket: if any other hearing for the same `hearing_officer_id` has a slot within 60 minutes of this one, the request is rejected with `ERR_HEARING_SLOT_CONFLICT`. Scheduling increments the enforcement's `version`. Hearings for an enforcement may be listed.

A `HearingOfficer` records the outcome of a pending hearing by supplying an `outcome` of `UPHELD`, `REDUCED`, `DISMISSED`, or `REMANDED` (and, for a reduction, a `reduction_pct`). Deciding requires the hearing to be `PENDING`, else `ERR_HEARING_NOT_PENDING`. Every outcome is subject to **segregation of duties**: the deciding `X-User-ID` must differ from the enforcement's `issued_by_user_id`, and a decision by the issuing officer is rejected with `ERR_SEGREGATION_OF_DUTIES`. Each decision stamps the hearing's `decided_at` with the logical clock and increments the enforcement's `version`.

The four outcomes differ in their effects. An **`UPHELD`** decision sets the hearing `PENDING → UPHELD`, moves the enforcement `HEARING_SCHEDULED → UPHELD`, and leaves `effective_fine_cents` unchanged. A **`REDUCED`** decision sets the hearing `PENDING → REDUCED` and the enforcement `HEARING_SCHEDULED → REDUCED`; it requires a `reduction_pct` that is a fraction at least 0 and strictly less than 1, else `ERR_REDUCTION_PCT_INVALID`. The reconciled fine becomes `assessed_fine_cents` multiplied by one minus `reduction_pct`, rounded half up to whole cents, and is written to `effective_fine_cents` (strictly less than the assessed amount whenever `reduction_pct` is above 0). If the payments already cleared exceed the new `effective_fine_cents` plus any `late_penalty_cents`, a refund row is created for exactly that surplus and the balance is recomputed. A **`DISMISSED`** decision sets the hearing `PENDING → DISMISSED` and the enforcement `HEARING_SCHEDULED → DISMISSED`; if any amount had been paid, a refund row is created for the full paid amount. Because the citation is now dismissed, the parcel's `substantiated_violation_count` is decremented and its `chronic_status` recomputed; if the count falls below the designation threshold and a `PENDING` abatement order with `trigger_source` `CHRONIC_DESIGNATION` exists for the parcel, that order is set to `VACATED` and the parcel's `abatement_status` returns to `NONE`. Both the enforcement's and the parcel's `version` increment. A **`REMANDED`** decision sets the hearing `PENDING → REMANDED` and returns the enforcement `HEARING_SCHEDULED → CONTESTED`, so a fresh hearing may be scheduled — this is the cyclic appeal loop.

### 3.7. Payments, Balances, and Late Penalties

The balance on a citation is always derived, never stored as a running figure. The `amount_paid_cents` on an enforcement equals the sum of all cleared `PAYMENT` ledger rows minus the sum of all cleared `REFUND` ledger rows. The `amount_outstanding_cents` equals `effective_fine_cents` plus `late_penalty_cents` minus `amount_paid_cents`. These are recomputed on read, so fetching an enforcement always reflects the live balance and any late penalty accrued to the current clock.

A `Resident` records a fine payment on an enforcement by supplying the `amount_cents` to apply, an optional `method` of `CARD`, `CHECK`, or `CASH` that defaults to `CARD`, and the `expected_enforcement_version` required by the concurrency guard in §2.8. The recorded row is a `PAYMENT` of `kind` with a `status` of `CLEARED`; refund rows, created only by hearing reductions and dismissals as described above, carry `kind` `REFUND`. A payment whose `amount_cents` exceeds the current `amount_outstanding_cents` is rejected with `ERR_PAYMENT_EXCEEDS_OUTSTANDING`. Each payment increments the enforcement's `version`, and when the outstanding balance reaches zero or below after a payment, the enforcement automatically moves to `PAID` (from `ISSUED`, `UPHELD`, or `REDUCED`). Ledger rows for an enforcement may be listed.

Late penalties accrue only after the due date. If the current clock is at or before `due_date`, `late_penalty_cents` is 0. Otherwise the number of whole overdue days is the elapsed time from `due_date` to now in seconds divided by 86,400 and rounded down. The per-day penalty is `effective_fine_cents` multiplied by 1.5% (0.015), rounded half up to whole cents. The total `late_penalty_cents` is that per-day penalty summed once for each overdue day — the per-day amount is rounded to whole cents **before** the days are summed, not after.

### 3.8. Chronic-Nuisance Designation and Abatement

Abatement orders arrive by two paths. The automatic path fires inside substantiation: when a parcel newly reaches `DESIGNATED`, an order with `trigger_source` `CHRONIC_DESIGNATION` is created in `PENDING` and the parcel enters `UNDER_ABATEMENT`, as described in §3.4. The manual path is driven by a `CodeOfficer`, who opens an order for a delinquent citation. The manual request supplies the `property_id`, the `expected_property_version` for the concurrency guard, an optional `enforcement_id` naming the delinquent citation that prompted the order, and an optional `compliance_deadline`. A manual order is stamped with `trigger_source` `DELINQUENT_CITATION`, moves the parcel to `UNDER_ABATEMENT`, and increments the parcel's `version`. If an `enforcement_id` is supplied it must belong to the same `property_id`, else `ERR_ENFORCEMENT_PROPERTY_MISMATCH`. When `compliance_deadline` is omitted it defaults to 30 days after the order's creation instant. Orders may be listed, optionally filtered by `property_id`, `enforcement_id`, or `status`, and fetched individually.

A `PENDING` order resolves in one of three ways. A `CodeOfficer` marks compliance, moving the order `PENDING → COMPLIED`; this requires the parcel's `abatement_status` to be `UNDER_ABATEMENT`, else `ERR_PROPERTY_NOT_UNDER_ABATEMENT`, and on success moves the parcel to `ABATED` and increments its `version`. A `CodeOfficer` escalates past-deadline non-compliance, moving the order `PENDING → ESCALATED`; escalation is permitted only when the current clock is at or after the `compliance_deadline`, and an earlier attempt is rejected with `ERR_ABATEMENT_DEADLINE_NOT_REACHED`. Finally, the system itself vacates an auto-created order (`PENDING → VACATED`) during a dismissal cascade, returning the parcel's `abatement_status` to `NONE` and incrementing its `version`.

### 3.9. Cross-Agency Referrals

Noise complaints frequently belong to another agency — a police matter, a building-code issue, a health concern, or an animal-control case. A `CodeOfficer` refers a complaint by naming the `complaint_id`, the receiving `agency` (one of `POLICE`, `BUILDING`, `HEALTH`, or `ANIMAL_CONTROL`), and an optional free-text `reason`. A referral opens in `OPEN`. A `CodeOfficer` acknowledges it (`OPEN → ACKNOWLEDGED`) and later closes it (`ACKNOWLEDGED → CLOSED`), or closes it directly from `OPEN`; a close may carry an optional `resolution` note. A transition that is not legal from the referral's current status is rejected with `ERR_REFERRAL_INVALID_STATE`. Referrals may be listed, optionally filtered by `complaint_id` or `status`, and fetched individually.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource (including state transitions and the clock control) return `200 OK`. The one exception among mutations is recording an inspection or a payment, which each create a new append-only record and therefore return `201 Created`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/properties` | Register a parcel | CodeOfficer, SystemAdmin |
| GET | `/properties` | List parcels | Any |
| GET | `/properties/{id}` | Get a parcel (posture + counts) | Any |
| POST | `/noise-policies` | Configure day/night decibel limits for a zoning_type | SystemAdmin |
| GET | `/noise-policies` | List configured policies | Any |
| POST | `/variance-permits` | Apply for a construction/event variance | Resident, PermitClerk |
| GET | `/variance-permits` | List variances | Any |
| GET | `/variance-permits/{id}` | Get a variance | Any |
| POST | `/variance-permits/{id}/issue` | Issue a variance | PermitClerk |
| POST | `/variance-permits/{id}/deny` | Deny a variance | PermitClerk |
| POST | `/variance-permits/{id}/revoke` | Revoke an issued variance | PermitClerk |
| POST | `/complaints` | Intake a noise complaint | Resident, CodeOfficer |
| GET | `/complaints` | List complaints | Any |
| GET | `/complaints/{id}` | Get a complaint | Any |
| POST | `/complaints/{id}/review` | Open a complaint for review | CodeOfficer |
| POST | `/complaints/{id}/inspections` | Record a field decibel reading | CodeOfficer |
| GET | `/complaints/{id}/inspections` | List readings for a complaint | Any |
| POST | `/complaints/{id}/substantiate` | Substantiate a complaint; issue an enforcement and cascade | CodeOfficer |
| POST | `/complaints/{id}/dismiss` | Dismiss a complaint | CodeOfficer |
| POST | `/referrals` | Refer a complaint to another agency | CodeOfficer |
| GET | `/referrals` | List referrals | Any |
| GET | `/referrals/{id}` | Get a referral | Any |
| POST | `/referrals/{id}/acknowledge` | Agency acknowledges a referral | CodeOfficer |
| POST | `/referrals/{id}/close` | Close a referral | CodeOfficer |
| GET | `/enforcements` | List enforcements | Any |
| GET | `/enforcements/{id}` | Get an enforcement (fine + live balance + late penalty) | Any |
| POST | `/enforcements/{id}/contest` | Appeal a citation | Resident |
| POST | `/enforcements/{id}/hearings` | Schedule an appeal hearing | HearingOfficer |
| GET | `/enforcements/{id}/hearings` | List hearings for an enforcement | Any |
| POST | `/enforcements/{id}/payments` | Record a fine payment (OCC-guarded) | Resident |
| GET | `/enforcements/{id}/payments` | List ledger rows for an enforcement | Any |
| POST | `/hearings/{id}/decide` | Record a hearing outcome | HearingOfficer |
| POST | `/abatement-orders` | Open a manual abatement order (OCC-guarded on Property) | CodeOfficer |
| GET | `/abatement-orders` | List abatement orders | Any |
| GET | `/abatement-orders/{id}` | Get an abatement order | Any |
| POST | `/abatement-orders/{id}/comply` | Mark compliance | CodeOfficer |
| POST | `/abatement-orders/{id}/escalate` | Escalate past-deadline non-compliance | CodeOfficer |
| POST | `/_clock/set_current_utc` | Set the server logical clock | SystemAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_INVALID_WINDOW` | 400 |
| `ERR_PROPERTY_NOT_FOUND` | 404 |
| `ERR_COMPLAINT_NOT_FOUND` | 404 |
| `ERR_VARIANCE_NOT_FOUND` | 404 |
| `ERR_ENFORCEMENT_NOT_FOUND` | 404 |
| `ERR_HEARING_NOT_FOUND` | 404 |
| `ERR_ABATEMENT_NOT_FOUND` | 404 |
| `ERR_REFERRAL_NOT_FOUND` | 404 |
| `ERR_DUPLICATE_POLICY` | 409 |
| `ERR_POLICY_NOT_CONFIGURED` | 409 |
| `ERR_ENFORCEMENT_PROPERTY_MISMATCH` | 409 |
| `ERR_COMPLAINT_NOT_UNDER_REVIEW` | 409 |
| `ERR_ENFORCEMENT_NOT_CITATION` | 409 |
| `ERR_ENFORCEMENT_NOT_CONTESTED` | 409 |
| `ERR_HEARING_NOT_PENDING` | 409 |
| `ERR_VARIANCE_NOT_UNDER_REVIEW` | 409 |
| `ERR_VARIANCE_NOT_ISSUED` | 409 |
| `ERR_PROPERTY_NOT_UNDER_ABATEMENT` | 409 |
| `ERR_REFERRAL_INVALID_STATE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VARIANCE_COVERS_COMPLAINT` | 409 |
| `ERR_VARIANCE_WINDOW_OVERLAP` | 409 |
| `ERR_HEARING_SLOT_CONFLICT` | 409 |
| `ERR_ABATEMENT_DEADLINE_NOT_REACHED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NO_INSPECTION_ON_RECORD` | 422 |
| `ERR_NOISE_WITHIN_LIMIT` | 422 |
| `ERR_VARIANCE_DB_EXCEEDS_CAP` | 422 |
| `ERR_REDUCTION_PCT_INVALID` | 422 |
| `ERR_PAYMENT_EXCEEDS_OUTSTANDING` | 402 |

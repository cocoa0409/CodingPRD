# Outpatient Clinic Registration API — Product Requirements Document

## 1. Introduction

A hospital's patient access department owns the front door of the outpatient revenue cycle. Long before a clinician enters the room, someone must register the patient without minting a duplicate medical record, discover and verify insurance coverage, confirm that referrals and prior authorizations are in place for the scheduled procedure, estimate and collect the patient's financial responsibility, and then move the arriving patient through a department queue while protecting the day's schedule against late arrivals and no-shows. Each step is a point of financial and compliance risk: a missed referral requirement becomes a payer denial weeks later, an uncollected deposit becomes bad debt, and a double-booked provider slot becomes lost capacity.

This document specifies the Outpatient Clinic Registration API, the system of record for that workflow, exposed under the `/patient-access` prefix. Four operator roles share the work under a segregation-of-duties model: registration staff own demographics, coverage, referrals, authorizations, and the schedule; financial counselors own estimates and point-of-service collection; front desk staff own arrival and the queue; and an access supervisor owns voids, deactivation, the logical clock, and day close. Every appointment carries a derived clearance gate that is recomputed whenever the facts beneath it change — a policy terminates, an authorization expires, a referral is matched, a payment posts — so that a visit can only advance toward the exam room when demographic, authorization, referral, and deposit obligations are all satisfied. Time itself is a governed input: the server evaluates every temporal rule against a logical clock rather than wall time, making eligibility staleness, document expiry, and no-show enforcement deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their operational role. The declared roles are `Registrar`, `FinancialCounselor`, `FrontDeskAgent`, and `AccessSupervisor`. A request whose headers are missing, or whose `X-User-Role` is not one of these declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

When `X-User-Role` is `Registrar`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it against a patient, an appointment, or any other resource `id`. The same holds when `X-User-Role` is `FinancialCounselor`, when it is `FrontDeskAgent`, and when it is `AccessSupervisor`: in all four cases the `X-User-ID` value is an opaque operator identifier with no entity backing, never used for ownership comparison against any persisted record.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from wall-clock time rather than the logical clock of §2.5.
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

Requests that match no declared route, or no declared method on a declared route, are rejected with `ERR_NOT_FOUND` (HTTP 404) in this same envelope, and an unexpected internal fault surfaces as `ERR_INVALID_REQUEST` with HTTP status 500.

### 2.3. Pagination

List endpoints are paginated through two query parameters. `limit` sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. A `limit` or `offset` that is not an integer, a `limit` outside its admitted range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order; resources created at the same instant retain their creation order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope, where `total_count` counts every matching resource before pagination and `has_more` is true exactly when matching resources remain beyond the returned page.

### 2.4. Common Resource Properties

Every resource in the system — Patient, InsurancePolicy, EligibilityCheck, Referral, Authorization, Appointment, CopayEstimate, Payment, QueueTicket, and AccommodationFlag — carries a uniform set of system-managed properties:

- `id`: a server-minted UUID with no type prefix, unique within the resource type.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created, stamped from the logical clock of §2.5.
- `updated_at`: an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification of the resource and likewise stamped from the logical clock.
- `version`: a system-managed integer that starts at 1 on creation and increments by one on every modification of the resource.

This convention applies uniformly, including when the change originates in a server-side cascade rather than a direct client write. Completing a patient's registration and merging a duplicate record each increment the patient's `version` by one; rescheduling an appointment increments the appointment's `version` by one. These two version-bearing fields are what the optimistic concurrency rules of §2.7 key on.

### 2.5. The Logical Clock

All time-dependent behavior — eligibility staleness, referral and authorization expiry, the late-arrival cutoff, and the no-show sweep — is evaluated against a server-maintained logical clock, never against the host's wall-clock time. Before it is ever set, the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall time afterward. An `AccessSupervisor`-only capability sets the clock to a supplied `to_iso8601` instant — any parseable instant is accepted, including one earlier than the current reading, and an ISO 8601 value without an explicit offset is read as UTC — and returns the resulting `current_utc`; that capability is the only way logical time moves. Advancing the logical date past a referral's or an authorization's validity boundary triggers the expiry cascades described in §3.3, which run as part of the set before the response returns.

### 2.6. Monetary Precision

Every monetary quantity in the API — allowed amounts, payer copays, deductible and out-of-pocket remainders, estimated responsibilities, deposit targets, tendered payments, and collected totals — is represented as an integer number of cents. Where a computation produces a fraction of a cent, the value is rounded half up to a whole cent, and for the estimate and deposit calculations that rounding is applied exactly once, at the final step of the calculation. Monetary inputs are range-checked on arrival: tendered amounts must be strictly greater than zero, while balance-style figures such as remaining deductible, remaining out-of-pocket maximum, payer copay, contracted allowed amount, and estimate results must be zero or greater.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and they are the only endpoints in the API that accept a version field. Rescheduling or editing an appointment (`PATCH /patient-access/appointments/{id}`) requires the request body to carry `expected_appointment_version`, holding the appointment `version` the client last observed. Merging a patient (`POST /patient-access/patients/{id}/merge`) requires `expected_patient_version`, holding the patient `version` the registrar last read. In both cases, if the supplied value does not match the resource's current `version` — meaning the record has advanced since the client's last read, for example because a clearance cascade recomputed the appointment after a policy termination or referral match — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The guard exists so that a caller acting on a stale snapshot cannot overwrite state it never observed. Endpoints not named here do not take a version field.

### 2.8. Clearance Recomputation and Cross-Entity Consistency

Every appointment carries a derived clearance snapshot — the persisted `registration_gate` and `auth_satisfied` fields — that the server recomputes immediately whenever an underlying fact changes: patient registration completion, an eligibility posting, an authorization being created, voided, or expired, a referral being matched, unmatched, or expired, an estimate being created or superseded, a payment being posted or voided, a policy termination, and a patient merge cascade. Recomputation is immediate, never deferred to a batch; a recomputation that leaves the persisted derived values unchanged is not itself a mutation and neither refreshes `updated_at` nor advances `version`, even when the triggering cascade rewrote other fields of the same record. State cascades flow outward from the changed record: terminating a policy supersedes the provisional estimates built on it, an expiring referral detaches from the future visits that referenced it, and a merge re-points the duplicate's appointments and policies to the surviving record. Each such reconciliation is itself a mutation on the affected resource, refreshing `updated_at` and advancing `version` per §2.4.

### 2.9. Nested Resource Retrieval

Requests that target nested resources are validated from left to right along the URL path: the server confirms the existence of each referenced identifier in order, and the first identifier that does not resolve to an existing resource rejects the request with `ERR_NOT_FOUND` (HTTP 404) before any later path segment or body reference is examined. The same existence discipline applies to identifiers carried in the request body — a payload referencing a nonexistent patient, appointment, policy, referral, authorization, ticket, or estimate fails with `ERR_NOT_FOUND` before business rules are evaluated.

### 2.10. Order of Validation

Validation runs in a fixed sequence on every request. Authentication of the operator headers comes first, then role authorization, then existence of every referenced resource, then the optimistic-concurrency check of §2.7 where it applies, then admissibility of the requested state transition — an action attempted against a resource in a state that does not permit it is rejected with `ERR_INVALID_STATE` (HTTP 409) — and only then the endpoint's remaining business rules. Where several business rules guard the same endpoint, their relative order is pinned in the workflow narratives of §3. Independently of that ordering, a request that is structurally malformed — a required field missing, a value of the wrong type, an unrecognized enumeration value, a numeric value outside its pinned range — is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Registration, Consent, and Duplicate Resolution

A `Registrar` opens the patient journey with pre-registration, supplying `first_name`, `last_name`, `date_of_birth` as an ISO calendar date in YYYY-MM-DD form, `sex_at_birth` as one of `M`, `F`, or `X`, and an E.164-formatted `primary_phone`; `email` is optional, and `language_code` records the patient's preferred ISO 639-1 language, defaulting to `en` and later driving the interpreter-flag default. On acceptance the server mints the patient's `mrn` — the literal prefix "MRN" followed by a zero-padded eight-digit sequence beginning at 00000001 and incrementing by one with each patient created — which is unique per patient and immutable once assigned, and the record enters `PRE_REGISTERED` status.

Duplicate prevention fires at creation. When an existing patient whose status is anything other than `MERGED` matches the newcomer on the exact triple of `first_name`, `last_name`, and `date_of_birth`, or matches on `primary_phone` alone, the create is rejected with `ERR_DUPLICATE_PATIENT` (HTTP 409). The match is exact — no fuzzy or phonetic comparison — and records already resolved as duplicates never block a new registration.

Registration completes when a `Registrar` captures consent against a record still in `PRE_REGISTERED`; a capture attempted against a record no longer in `PRE_REGISTERED` is rejected with `ERR_INVALID_STATE` (HTTP 409). Two conditions gate the transition: the five core demographics — `first_name`, `last_name`, `date_of_birth`, `sex_at_birth`, and `primary_phone` — must all be non-empty, and the payload must carry `consent_general` as true; a violation of either condition is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The same capture may optionally record `consent_financial` and refresh `primary_phone` or `email`. Completion moves the patient `PRE_REGISTERED` → `REGISTERED`, increments the patient `version` by one, and forces a clearance recomputation on every appointment the patient holds in `SCHEDULED`, because demographic clearance is one of the gate's inputs.

Duplicate records that slip through are resolved by merging. A `Registrar` merges the duplicate into a survivor named by `survivor_patient_id`, which must reference a different patient whose status is not `MERGED`; the duplicate itself may be in either `PRE_REGISTERED` or `REGISTERED`. A `survivor_patient_id` identical to the duplicate's own id is rejected with `ERR_INVALID_REQUEST` (HTTP 400) ahead of the version check, while a duplicate outside those two statuses or a survivor already `MERGED` is rejected with `ERR_INVALID_STATE` (HTTP 409). Because a merge re-points live business, the request is OCC-guarded: it must carry `expected_patient_version` matching the duplicate record's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful merge stamps the duplicate's `duplicate_of_patient_id` with the survivor's id, moves the duplicate to the terminal `MERGED` status, increments its `version` by one, re-points every appointment of the duplicate in `SCHEDULED`, `PRE_CHECKED`, or `READY` to the survivor with clearance recomputed on each, re-points every insurance policy of the duplicate to the survivor, and re-runs referral matching on the moved appointments.

An `AccessSupervisor` may retire a `REGISTERED` patient to the terminal `INACTIVE` status, but only while the patient holds no appointment in `SCHEDULED`, `PRE_CHECKED`, `READY`, `ARRIVED`, or `IN_ROOM`. Deactivation changes nothing else — it simply closes the record to further work.

The patient roster supports filtered listing by `status`, `last_name`, `date_of_birth`, or `duplicate_of_patient_id`, alongside the standard pagination parameters.

Accessibility needs travel with the patient as accommodation flags. A `Registrar` attaches a flag with a `flag_type` of `INTERPRETER`, `MOBILITY`, `SENSORY`, or `COGNITIVE`; an `INTERPRETER` flag must carry a `language_code`, and omitting it is rejected with `ERR_LANGUAGE_REQUIRED` (HTTP 400), while other flag types may leave `language_code` null. An optional free-text `note` carries instructions for the care team. Flags are born with `active` set to true; a `Registrar` or an `AccessSupervisor` may later deactivate one, which soft-deletes it — `active` becomes false — so it no longer counts toward queue priority at check-in; deactivating a flag that is already inactive succeeds without further change. The flag listing under a patient can be narrowed with the `active` filter, which accepts the strings `true` and `false` case-insensitively and ignores any other value.

### 3.2. Insurance Policies and Eligibility Verification

Coverage is recorded by a `Registrar` as an insurance policy carrying the `patient_id` of the policyholder, the external `payer_id`, the subscriber's `member_id` from the plan card, and an optional `group_number`. The `plan_type` — one of `HMO`, `PPO`, `EPO`, `POS`, `MEDICARE`, `MEDICAID`, or `SELF_PAY` — later decides whether visits booked against this policy require a matched referral. Coverage runs from `effective_start` inclusive through `effective_end` inclusive; `effective_end` may be null for open-ended coverage, but when present it must not fall before `effective_start`, and a violation is rejected with `ERR_INVALID_DATE_RANGE` (HTTP 400). Coordination of benefits is expressed through `priority_rank`, an integer of at least 1 where 1 designates the primary policy and 2 the secondary; the rank must be unique among the patient's policies that are not `VOIDED`, otherwise the create fails with `ERR_PRIORITY_RANK_CONFLICT` (HTTP 409). On policy creation the date-range check is evaluated before the rank-uniqueness check, so an inverted coverage window surfaces as `ERR_INVALID_DATE_RANGE` even when the requested rank would also collide. The financial baseline fields `deductible_remaining_cents` and `oop_max_remaining_cents` capture the remaining individual deductible and remaining out-of-pocket maximum at verification time, each zero or greater. New policies are born `ACTIVE`, and a patient's policies are listed under the patient record with an optional `status` filter.

Termination and voiding are deliberately different acts. A `Registrar` terminates an `ACTIVE` policy by supplying an `effective_end` in the payload that falls on or after the policy's `effective_start`; the policy stores that end date and moves `ACTIVE` → `TERMINATED`. Termination cascades: every appointment of the policy's patient in `SCHEDULED` or `PRE_CHECKED` that relies on a `PROVISIONAL` estimate built from this policy has that estimate moved to `SUPERSEDED`, the appointment's cached responsibility re-derived, and its clearance recomputed. An `AccessSupervisor` instead voids a policy — `ACTIVE` → `VOIDED` — only when no eligibility check with `coverage_status` of `ACTIVE` has ever been posted against it; voiding releases the policy's `priority_rank` slot for reuse by a future policy. Terminating a policy that is not `ACTIVE`, or voiding one that is not `ACTIVE` or that carries such a check, is rejected with `ERR_INVALID_STATE` (HTTP 409).

Eligibility is verified by posting a payer response against a (`policy_id`, `appointment_id`) pair. The referenced policy must belong to the same patient as the referenced appointment; a cross-patient mismatch is rejected with `ERR_CROSS_PATIENT_REFERENCE` (HTTP 422). The posting is accepted regardless of the policy's status or the appointment's status. The posting records the payer-reported `coverage_status` — one of `ACTIVE`, `INACTIVE`, `NOT_FOUND`, or `UNKNOWN` — together with `copay_cents` at zero or greater, `coinsurance_pct` between 0 and 100 inclusive, and `auth_required`, which tells whether the payer flags the scheduled procedure as needing prior authorization. The server stamps `checked_at` with the transaction time and derives the check's `result`: any `coverage_status` other than `ACTIVE` yields `FAILED`; otherwise an `auth_required` flag yields `VERIFIED_WITH_AUTH`; a clean active response yields `VERIFIED`.

Verification does not age gracefully. A stored check flips to `STALE` when the current logical date falls strictly more than thirty days after the date of its `checked_at`; a check exactly thirty days old is still fresh. Staleness is recomputed lazily — when the check is read and again during clearance sweeps — rather than by any batch job. Posting a check also recomputes the appointment's clearance snapshot, and each posting is retrievable both under its policy and under its appointment.

### 3.3. Referrals and Prior Authorizations

Inbound referrals and orders are registered by a `Registrar` with the referred `patient_id`, the ordering provider's `referring_provider_npi`, the target `specialty_code` (for example, CARD for cardiology), the `procedure_code` the referral authorizes, and a `visits_authorized` count of at least one. The referral is usable from `valid_from` inclusive through `valid_until` inclusive, and a window whose start falls after its end is rejected with `ERR_INVALID_DATE_RANGE` (HTTP 400). A new referral starts with `visits_consumed` at zero and status `OPEN`, and its arrival re-runs referral matching for the patient's still-unmatched appointments.

Matching is deterministic and runs whenever an appointment is created or edited, when a patient merge moves appointments, when a referral is created, and when a referral expires; only appointments in `SCHEDULED`, `PRE_CHECKED`, or `READY` participate, and an appointment in any later state never gains or loses its `referral_id` through a matching sweep. The candidate set for an appointment comprises the patient's `OPEN` referrals whose `specialty_code` equals the appointment's `department_code`, whose `procedure_code` equals the appointment's `procedure_code`, whose validity window contains the appointment's scheduled date — `valid_from` on or before that date and `valid_until` on or after it — and which still show `visits_consumed` below `visits_authorized`. Candidates are ranked lexicographically: a referral whose `referring_provider_npi` matches the appointment's `referring_provider_npi` outranks one that does not; ties break toward the earliest `valid_until`; remaining ties break toward the oldest `created_at`. The winner is pinned on the appointment as `referral_id`. An empty candidate set is not an error — `referral_id` simply stays null, though the clearance gate may remain `BLOCKED` as a consequence.

Referrals end in three ways. When a check-in increments `visits_consumed` so that it reaches `visits_authorized`, the referral moves `OPEN` → `EXHAUSTED` and future matching sweeps skip it. When the logical clock advances past `valid_until`, the referral moves `OPEN` → `EXPIRED`, and every appointment still referencing it in `SCHEDULED` or `PRE_CHECKED` has its `referral_id` cleared and its clearance recomputed. A `Registrar` may instead close an `OPEN` referral manually — `OPEN` → `CLOSED`, and closing a referral that is not `OPEN` is rejected with `ERR_INVALID_STATE` (HTTP 409); appointments referencing it in `SCHEDULED` or `PRE_CHECKED` keep the match as historical fact, but matching will not re-attach the referral if that match is later cleared. A patient's referrals are listed under the patient record with an optional `status` filter.

Prior authorizations follow a parallel shape. A `Registrar` records one with the `patient_id`, the covered `appointment_id`, the payer-issued `payer_auth_number`, an `authorized_units` count of at least one, and the `valid_until` expiry date; the appointment may be in any status, and the payload's `patient_id` is not cross-checked against the appointment's patient. The authorization enters `APPROVED` immediately, and its arrival recomputes the appointment's clearance, which may flip `auth_satisfied` to true. At check-in, the authorization covering the visit — the one whose `appointment_id` matches the arriving appointment and from which `auth_satisfied` was derived — moves `APPROVED` → `CONSUMED`. When the logical clock advances past an authorization's `valid_until`, it moves `APPROVED` → `EXPIRED` and the owning appointment's clearance is recomputed, which may flip `auth_satisfied` back to false. An `AccessSupervisor` may void an `APPROVED` authorization — `APPROVED` → `VOIDED` — which likewise recomputes the owning appointment's clearance. Authorizations are listed both under their appointment and under their patient, each with an optional `status` filter.

These two artifacts stand guard at readiness time. When the primary policy's `plan_type` is `HMO` or `EPO` and no referral is matched to the visit, marking it ready is rejected with `ERR_REFERRAL_REQUIRED` (HTTP 422). When the visit requires prior authorization and no current `APPROVED` authorization covers it, the rejection is `ERR_AUTH_REQUIRED` (HTTP 422). The full gate derivation, and the order in which these guardrails fire, is pinned in §3.5.

### 3.4. Scheduling and Visit Preparation

A `Registrar` books a visit with the `patient_id`, the `department_code` of the clinic (which mirrors referral specialty codes), the scheduled `procedure_code`, the `scheduled_start` instant in UTC, a `duration_minutes` slot length of at least five minutes, the `visit_type` — one of `NEW`, `ESTABLISHED`, `PROCEDURE`, or `IMAGING`, a category that drives both the copay schedule and the authorization rules — and the `provider_code` of the rendering resource. An optional `referring_provider_npi` records the NPI on the order and feeds referral matching. Booking imposes no constraint on the patient's status and immediately runs referral matching, computes the initial clearance snapshot, and computes the patient's trailing no-show strike count, stored on the appointment as `no_show_risk_strikes`. New appointments enter `SCHEDULED`, and a freshly booked visit carries zeroed financials — `estimated_patient_responsibility_cents` and `amount_collected_cents` both at 0 — with `late_minutes` at 0 until check-in, `auth_satisfied` false unless the initial derivation already satisfies it, and `registration_gate` beginning at `BLOCKED` until that first clearance computation resolves it.

Provider capacity is protected from the moment of booking. Two appointments that are both live — each in `SCHEDULED`, `PRE_CHECKED`, `READY`, `ARRIVED`, or `IN_ROOM` — may not overlap for the same `provider_code`, where an appointment occupies the interval from its `scheduled_start` up to but not including its `scheduled_start` plus `duration_minutes`. Intervals that merely touch, one beginning exactly when the other ends, do not overlap. A colliding booking is rejected with `ERR_PROVIDER_DOUBLE_BOOKED` (HTTP 409), and the overlap check is evaluated before temporal sanity: a slot that collides surfaces `ERR_PROVIDER_DOUBLE_BOOKED` even when its start would also fail the date rule. Temporal sanity requires the `scheduled_start` to fall on or after the current logical date; a start in the past is rejected with `ERR_INVALID_DATE_RANGE` (HTTP 400).

Rescheduling or editing an appointment is a `Registrar` act guarded by optimistic concurrency. The request must carry `expected_appointment_version` equal to the appointment's current `version`; a value left behind by an intervening write is rejected with `ERR_STALE_VERSION` (HTTP 412). Any of `scheduled_start`, `duration_minutes`, `provider_code`, `department_code`, `procedure_code`, `visit_type`, or `referring_provider_npi` may change in a single edit, and the edit is admitted whatever the appointment's current status. A successful edit increments the appointment `version` by one — plus one more when the recomputed clearance snapshot actually changes the derived fields, per §2.8 — re-runs referral matching, recomputes the clearance snapshot, and re-validates double-booking with the appointment itself excluded from the overlap scan, again evaluated ahead of the date-range rule.

Once coverage is verified, a `Registrar` advances the visit `SCHEDULED` → `PRE_CHECKED`. Pre-check requires the patient to be `REGISTERED` and a usable verification on file: an eligibility check for this appointment whose `result` is `VERIFIED` or `VERIFIED_WITH_AUTH` and whose `checked_at` falls within thirty days of the current date. A pre-check attempted from a state other than `SCHEDULED`, against a patient who is not `REGISTERED`, or without a usable verification is rejected with `ERR_INVALID_STATE` (HTTP 409). Pre-check recomputes clearance. When plans change, the same role reverts the visit `PRE_CHECKED` → `SCHEDULED`, again recomputing clearance.

Cancellation is available to a `Registrar` from any pre-arrival state — `SCHEDULED`, `PRE_CHECKED`, or `READY` — and lands the appointment in the terminal `CANCELLED` status, with an optional `reason` recorded on the appointment as `cancel_reason`. Payments already `POSTED` against the visit are left untouched; refunding is a separate, explicit act. If a queue ticket for the appointment were waiting, cancellation removes it. The appointment book supports filtered listing by `patient_id`, `provider_code`, `department_code`, `status`, calendar `date` — matched against the UTC calendar date of `scheduled_start` — or `referral_id`, and each patient's visits are also listed under the patient record with an optional `status` filter.

### 3.5. Estimating Responsibility and Collecting Payment

A `FinancialCounselor` creates a copay estimate for an appointment by naming the `policy_id` to bill and the contracted `allowed_amount_cents` for the procedure, at zero or greater. The named policy must belong to the appointment's patient — a mismatch is rejected with `ERR_CROSS_PATIENT_REFERENCE` (HTTP 422) — and must be `ACTIVE`, with any other policy status rejected with `ERR_INVALID_STATE` (HTTP 409); the appointment's own status is not constrained. The estimate's `method` records which of two variants produced the numbers. `PAYER_VERIFIED` applies when a usable verification exists: an eligibility check for this appointment and policy whose result is not `STALE` and whose `coverage_status` is `ACTIVE`, and when several such checks exist the payer-reported values are taken from the latest one posted. `FEE_SCHEDULE` applies when no usable verification exists, and it ignores payer-reported fields entirely.

Under `PAYER_VERIFIED`, the payer-reported `copay_cents` is taken as the patient's responsibility. When that copay is zero, the estimate instead follows the deductible-then-coinsurance path: the deductible portion is the lesser of `allowed_amount_cents` and the policy's `deductible_remaining_cents`, and the responsibility becomes that deductible portion plus the coinsurance increment — the allowed amount beyond the deductible portion, multiplied by `coinsurance_pct` and divided by one hundred, rounded half up to a whole cent. In either case the responsibility is then capped at the policy's `oop_max_remaining_cents`.

Under `FEE_SCHEDULE`, a flat base fee is selected by `visit_type`: 22000 cents for a `NEW` visit, 14000 cents for `ESTABLISHED`, 45000 cents for `PROCEDURE`, and 38000 cents for `IMAGING`. The base is then multiplied by a loading factor — 1.0 for `ESTABLISHED` visits, and the new-patient loading of 1.2 for every other visit type — and the product is rounded half up to a whole cent.

Whichever variant ran, a deposit target is pinned immediately afterward, tiered by the patient's no-show risk. The strike count comes from the same rule that feeds `no_show_risk_strikes`: the number of the patient's appointments in `NO_SHOW` status whose `scheduled_start` falls inside the trailing 365-day half-open window ending at the as-of instant — a no-show scheduled exactly 365 days before the as-of instant counts, while one scheduled exactly at the as-of instant does not. With at least two strikes, the deposit target is the full estimate — one hundred percent of it. Below that threshold, a `NEW` visit owes fifty percent of the estimate, and any other visit type owes twenty-five percent. The target is stored on the estimate as `deposit_required_cents`, the estimate's own result as `estimated_patient_responsibility_cents`, and both are whole-cent figures produced by a single final round-half-up. The strike count is also computed at appointment creation and recomputed whenever a new no-show lands.

Estimates are provisional until proven. Creating a newer estimate for the same appointment moves every prior `PROVISIONAL` estimate of that appointment to `SUPERSEDED`, and the policy-termination cascade of §3.2 does the same; the appointment's cached `estimated_patient_responsibility_cents` is then re-derived from the newest `PROVISIONAL` estimate, falling back to zero when none remains, and clearance is recomputed. When the visit later completes, the latest `PROVISIONAL` estimate moves to `FINAL`, and the appointment's cached responsibility is re-pinned to the finalized estimate's value without numeric change. Estimates are retrievable both under their appointment and under the policy that produced them, each listing accepting an optional `status` filter.

The clearance gate ties all of these threads together, and its evaluation order is pinned. First, authorization need is established: an authorization is needed when the `visit_type` is `PROCEDURE` or `IMAGING`, or when the latest non-`STALE` eligibility check for the visit carries `auth_required` as true. Second, `auth_satisfied` is true when no authorization is needed, or when an authorization exists for this appointment in `APPROVED` status whose `valid_until` falls on or after the appointment date. Third, a referral is needed when the patient's primary policy — the non-`VOIDED` policy with `priority_rank` 1 — has a `plan_type` of `HMO` or `EPO`. Fourth, that referral need is satisfied when it does not apply or when the appointment's `referral_id` is set. Fifth, demographic clearance requires the patient's status to be `REGISTERED`. Sixth, the current estimate is the latest non-`SUPERSEDED` estimate for the visit. Finally the gate resolves: when demographics, authorization, and referral are not all satisfied, `registration_gate` is `BLOCKED`; otherwise, when a current estimate exists whose `deposit_required_cents` is above zero and `amount_collected_cents` has not yet reached it, the gate is `CLEAR_WITH_PAYMENT`; otherwise the gate is `CLEAR`. Both derived fields are persisted on the appointment after every triggering event enumerated in §2.8.

Collection happens through payments posted by a `FinancialCounselor`. Each payment carries an `amount_cents` strictly greater than zero, a tender `method` of `CASH`, `CARD`, `CHECK`, or `WALLET`, and a `kind` of POST for a point-of-service collection or REFUND for a compensation reversing a prior collection; payments enter `POSTED` status, and posting is accepted whatever the appointment's current status. A refund may not exceed the visit's current `amount_collected_cents`, although refunding down to exactly zero is allowed; an over-large refund is rejected with `ERR_REFUND_EXCEEDS_COLLECTED` (HTTP 422). The collected total itself is recomputed in full — never adjusted incrementally — on every payment posting and every void: it is the sum of `amount_cents` over the appointment's `POSTED` payments of kind POST, minus the sum over its `POSTED` payments of kind REFUND, clamped so it never falls below zero. Posting also recomputes clearance, so a `CLEAR_WITH_PAYMENT` gate relaxes to `CLEAR` the moment enough money has landed. An `AccessSupervisor` may void a `POSTED` payment — `POSTED` → `VOIDED` — which recomputes the collected total and the clearance gate in exactly the same way. Payments are listed under their appointment.

Readiness is the financial gatekeeper's sign-off. A `FinancialCounselor` moves a `PRE_CHECKED` visit to `READY` only when the gate allows it: either `registration_gate` is `CLEAR`, or it is `CLEAR_WITH_PAYMENT` and `amount_collected_cents` has reached the `deposit_required_cents` of the latest non-`SUPERSEDED` estimate. The guardrails fire in a pinned order. The referral requirement is evaluated first, so an `HMO` or `EPO` visit without a matched referral is rejected with `ERR_REFERRAL_REQUIRED` even when money is also outstanding. Next comes the authorization requirement, rejecting with `ERR_AUTH_REQUIRED` when a `PROCEDURE` or `IMAGING` visit — or one the payer flagged through `auth_required` — lacks a current `APPROVED` authorization. Only then does the collection requirement fire, rejecting with `ERR_DEPOSIT_SHORTFALL` (HTTP 402) while collected funds remain below the deposit target. A visit whose gate is `BLOCKED` on any other ground is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.6. Arrival, Check-In, and the Department Queue

On arrival day a `FrontDeskAgent` checks the patient in, moving the visit `READY` → `ARRIVED`; the optional `stat_flag` payload marks the arrival for priority transport. Two guards fire first, in a pinned order. Queue uniqueness comes before the clock: an appointment may hold at most one ticket in `WAITING` or `CALLED` state, and a check-in attempt against an appointment that already has one is rejected with `ERR_TICKET_ALREADY_ACTIVE` (HTTP 409). Then the late-arrival rule applies: check-in is rejected with `ERR_TOO_LATE_FOR_CHECKIN` (HTTP 422) once the current time passes thirty minutes after `scheduled_start`, while an arrival exactly thirty minutes late is still accepted. A successful check-in returns the updated appointment and records `late_minutes` on it — the signed elapsed time between `scheduled_start` and the actual check-in, floored to whole minutes and negative when the patient arrived early.

Check-in also issues the day's queue ticket. The ticket copies `department_code` from the appointment and derives `queue_date` — the UTC calendar date of the visit's `scheduled_start` — from `scheduled_start`; the queue is per department per day. Its `sequence_number` is one more than the count of tickets already issued for that department and date in any state, so numbers are monotonic within the day and never reused, even after tickets are skipped or removed. The ticket's `priority` is derived at issuance: `STAT` when the check-in payload carried `stat_flag` as true; otherwise `ACCOMMODATION` when the patient has any accommodation flag with `active` set to true; otherwise `STANDARD` — `STAT` outranks all, and `ACCOMMODATION` outranks `STANDARD`. The ticket starts `WAITING` with `called_at` null. Two consumptions ride along with arrival: the matched referral's `visits_consumed` increments by one while that referral is still `OPEN` — a match retained as historical fact on a `CLOSED` referral is not incremented — which may tip it into `EXHAUSTED` per §3.3, and the authorization covering the visit moves `APPROVED` → `CONSUMED`.

Rooming runs off the queue. Calling the next patient requires the `department_code` and the `queue_date` in the request body, and selects among that day's `WAITING` tickets for the department by priority rank — `STAT` first, then `ACCOMMODATION`, then `STANDARD` — breaking ties by ascending `sequence_number`; the first ticket in that order is called. The called ticket moves `WAITING` → `CALLED` with `called_at` stamped by the server, its owning appointment moves `ARRIVED` → `IN_ROOM`, and the response carries the ticket; a skip likewise returns the ticket. Calling next against an empty queue — no `WAITING` ticket exists for the department and date — is rejected with `ERR_QUEUE_EMPTY` (HTTP 404). When a called patient cannot be roomed, a `FrontDeskAgent` skips the ticket, moving it `CALLED` → `SKIPPED`, and the appointment drops back from `IN_ROOM` to `ARRIVED` for re-rooming.

Finishing the visit is a `FrontDeskAgent` act from `IN_ROOM` to the terminal `COMPLETED` status: the ticket moves `CALLED` → `SERVED`, and the visit's latest `PROVISIONAL` estimate moves to `FINAL` as described in §3.5. A ticket still `WAITING` is removed — `WAITING` → `REMOVED` — if its owning appointment leaves `ARRIVED` through cancellation or no-show. The day's queue for a department is listed by `queue_date`, a required query parameter whose absence is rejected with `ERR_INVALID_REQUEST` (HTTP 400), with an optional `state` filter; departments are not persisted resources, so an unrecognized `department_code` simply yields an empty page. An appointment's tickets are listed under the appointment.

### 3.7. No-Show Administration and Day Close

Visits that never materialize are marked `NO_SHOW` from any pre-arrival state — `SCHEDULED`, `PRE_CHECKED`, or `READY` — once the current time reaches the `scheduled_start` plus the configured no-show grace period of thirty minutes. A `FrontDeskAgent` may mark an individual visit any time after that grace moment, and a marking attempted before it is rejected with `ERR_INVALID_STATE` (HTTP 409); alternatively the day-close sweep marks them in bulk. Every no-show recomputes the patient's trailing strike count as it applies to future appointments — refreshing `no_show_risk_strikes` on the patient's pre-arrival appointments only — which in turn pushes those visits' deposit targets toward the high-risk tier of §3.5: targets already pinned on existing estimates are left unchanged, and only estimates created afterward observe the new count. `COMPLETED`, `CANCELLED`, and `NO_SHOW` are the terminal states of the appointment lifecycle.

Day close is an `AccessSupervisor` sweep run per department for a `queue_date` supplied in the request body. It marks every appointment of the department still in `SCHEDULED`, `PRE_CHECKED`, or `READY` whose grace moment has passed as `NO_SHOW`, and removes every `WAITING` ticket of that date from the queue, moving each to `REMOVED`. The sweep reports back the number of visits marked as `no_show_count` and the number of tickets expired out of the queue as `expired_ticket_count`. Together with the logical-clock capability of §2.5 — which flips referrals and authorizations into `EXPIRED` as their validity dates pass — day close is how the department rolls the calendar forward.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource or drive a state transition — including completions, merges, voids, sweeps, and clock adjustments — return a `200 OK` status code. The table below summarizes the HTTP contract only; the request payloads, derived fields, and side effects of each operation are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/patient-access/_clock/set_current_utc` | Set the server's logical clock (default before any set: 2026-08-01T00:00:00Z) | AccessSupervisor |
| POST | `/patient-access/patients` | Pre-register a patient, minting the MRN; rejects duplicate demographics | Registrar |
| GET | `/patient-access/patients` | List patients with pagination and optional filters | Registrar, FinancialCounselor, FrontDeskAgent, AccessSupervisor |
| GET | `/patient-access/patients/{id}` | Fetch one patient | Registrar, FinancialCounselor, FrontDeskAgent, AccessSupervisor |
| POST | `/patient-access/patients/{id}/complete-registration` | Capture demographics and consent; PRE_REGISTERED → REGISTERED | Registrar |
| POST | `/patient-access/patients/{id}/merge` | Resolve a duplicate by merging this patient into a survivor record (OCC-guarded) | Registrar |
| POST | `/patient-access/patients/{id}/deactivate` | REGISTERED → INACTIVE when no live appointments remain | AccessSupervisor |
| GET | `/patient-access/patients/{id}/appointments` | Reverse lookup: appointments of a patient | Registrar, FinancialCounselor, FrontDeskAgent, AccessSupervisor |
| GET | `/patient-access/patients/{id}/insurance-policies` | Reverse lookup: policies of a patient | Registrar, FinancialCounselor, AccessSupervisor |
| GET | `/patient-access/patients/{id}/referrals` | Reverse lookup: referrals of a patient | Registrar, FinancialCounselor, AccessSupervisor |
| GET | `/patient-access/patients/{id}/accommodation-flags` | Reverse lookup: accommodation flags of a patient | Registrar, FrontDeskAgent, AccessSupervisor |
| POST | `/patient-access/patients/{id}/accommodation-flags` | Attach an interpreter, mobility, sensory, or cognitive flag | Registrar |
| POST | `/patient-access/accommodation-flags/{id}/deactivate` | Soft-deactivate a flag | Registrar, AccessSupervisor |
| POST | `/patient-access/insurance-policies` | Add a coverage policy for a patient | Registrar |
| GET | `/patient-access/insurance-policies/{id}` | Fetch one policy | Registrar, FinancialCounselor, AccessSupervisor |
| GET | `/patient-access/insurance-policies/{id}/eligibility-checks` | Reverse lookup: eligibility checks posted against a policy | Registrar, FinancialCounselor, AccessSupervisor |
| GET | `/patient-access/insurance-policies/{id}/copay-estimates` | Reverse lookup: estimates computed from a policy | Registrar, FinancialCounselor, AccessSupervisor |
| POST | `/patient-access/insurance-policies/{id}/terminate` | ACTIVE → TERMINATED, superseding provisional estimates | Registrar |
| POST | `/patient-access/insurance-policies/{id}/void` | ACTIVE → VOIDED when the policy was never verified | AccessSupervisor |
| POST | `/patient-access/referrals` | Register an inbound referral or order | Registrar |
| GET | `/patient-access/referrals/{id}` | Fetch one referral | Registrar, FinancialCounselor, AccessSupervisor |
| POST | `/patient-access/referrals/{id}/close` | OPEN → CLOSED | Registrar |
| POST | `/patient-access/authorizations` | Record a payer authorization for a visit | Registrar |
| GET | `/patient-access/authorizations/{id}` | Fetch one authorization | Registrar, FinancialCounselor, AccessSupervisor |
| GET | `/patient-access/appointments/{id}/authorizations` | Reverse lookup: authorizations of an appointment | Registrar, FinancialCounselor, AccessSupervisor |
| GET | `/patient-access/patients/{id}/authorizations` | Reverse lookup: authorizations of a patient | Registrar, FinancialCounselor, AccessSupervisor |
| POST | `/patient-access/authorizations/{id}/void` | APPROVED → VOIDED; clearance recomputed | AccessSupervisor |
| POST | `/patient-access/appointments` | Schedule a visit; runs referral matching and initial clearance | Registrar |
| GET | `/patient-access/appointments/{id}` | Fetch one appointment with derived fields | Registrar, FinancialCounselor, FrontDeskAgent, AccessSupervisor |
| GET | `/patient-access/appointments` | List appointments with filters | Registrar, FinancialCounselor, FrontDeskAgent, AccessSupervisor |
| PATCH | `/patient-access/appointments/{id}` | Reschedule or edit an appointment (OCC-guarded) | Registrar |
| POST | `/patient-access/appointments/{id}/pre-check` | SCHEDULED → PRE_CHECKED once eligibility is verified | Registrar |
| POST | `/patient-access/appointments/{id}/revert-precheck` | PRE_CHECKED → SCHEDULED | Registrar |
| POST | `/patient-access/appointments/{id}/mark-ready` | PRE_CHECKED → READY when the gate is CLEAR or the deposit is satisfied | FinancialCounselor |
| POST | `/patient-access/appointments/{id}/check-in` | READY → ARRIVED; issues a queue ticket and consumes referral and authorization | FrontDeskAgent |
| POST | `/patient-access/appointments/{id}/complete` | IN_ROOM → COMPLETED; ticket served; estimate finalized | FrontDeskAgent |
| POST | `/patient-access/appointments/{id}/cancel` | Cancel from any pre-arrival state | Registrar |
| POST | `/patient-access/appointments/{id}/mark-no-show` | Manual no-show marking after the grace period | FrontDeskAgent |
| GET | `/patient-access/appointments/{id}/copay-estimates` | Reverse lookup: estimates of an appointment | Registrar, FinancialCounselor, AccessSupervisor |
| GET | `/patient-access/appointments/{id}/payments` | Reverse lookup: payments of an appointment | Registrar, FinancialCounselor, AccessSupervisor |
| GET | `/patient-access/appointments/{id}/queue-tickets` | Reverse lookup: queue tickets of an appointment | FrontDeskAgent, AccessSupervisor |
| GET | `/patient-access/appointments/{id}/eligibility-checks` | Reverse lookup: eligibility checks of an appointment | Registrar, FinancialCounselor, AccessSupervisor |
| POST | `/patient-access/eligibility-checks` | Post a payer eligibility response for an appointment and policy | Registrar |
| POST | `/patient-access/appointments/{id}/copay-estimates` | Create an estimate; supersedes prior provisional estimates | FinancialCounselor |
| POST | `/patient-access/appointments/{id}/payments` | Post a point-of-service collection or refund | FinancialCounselor |
| POST | `/patient-access/payments/{id}/void` | Void a posted payment | AccessSupervisor |
| POST | `/patient-access/queue-tickets/call-next` | Pop the next waiting ticket per the selector; appointment ARRIVED → IN_ROOM | FrontDeskAgent |
| POST | `/patient-access/queue-tickets/{id}/skip` | CALLED → SKIPPED; appointment returns to ARRIVED for re-rooming | FrontDeskAgent |
| GET | `/patient-access/departments/{department_code}/queue` | List the day's queue for a department | FrontDeskAgent, AccessSupervisor |
| POST | `/patient-access/departments/{department_code}/close-day` | Ops-run sweep: mark no-shows for the date and expire stale queue tickets | AccessSupervisor |

## 5. Error Code Catalogue

The trigger condition for each error is specified in the narratives of §2 and §3; this catalogue fixes only the identifier and the HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE_PATIENT` | 409 |
| `ERR_REFERRAL_REQUIRED` | 422 |
| `ERR_AUTH_REQUIRED` | 422 |
| `ERR_PROVIDER_DOUBLE_BOOKED` | 409 |
| `ERR_TICKET_ALREADY_ACTIVE` | 409 |
| `ERR_LANGUAGE_REQUIRED` | 400 |
| `ERR_INVALID_DATE_RANGE` | 400 |
| `ERR_TOO_LATE_FOR_CHECKIN` | 422 |
| `ERR_DEPOSIT_SHORTFALL` | 402 |
| `ERR_REFUND_EXCEEDS_COLLECTED` | 422 |
| `ERR_PRIORITY_RANK_CONFLICT` | 409 |
| `ERR_CROSS_PATIENT_REFERENCE` | 422 |
| `ERR_QUEUE_EMPTY` | 404 |

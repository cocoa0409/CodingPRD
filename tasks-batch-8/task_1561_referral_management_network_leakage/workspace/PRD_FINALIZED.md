# Referral Management & Network Leakage API — Product Requirements Document

## 1. Introduction

Health systems lose substantial downstream revenue when referred patients drift out of network, never book, or quietly fall through an untracked follow-up gap. A referral center sits between community physicians and employed specialists, and its leverage depends on three things happening reliably: the right specialist is matched to each order, the appointment actually occurs, and the consult note comes back so the loop can be verified closed. When any of those steps fails silently, the visit — and the revenue attached to it — leaks to a competitor.

This document specifies a Referral Management & Network Leakage API that supports the full closed-loop lifecycle: referral order creation with specialty matching, in-network preference and patient-choice documentation, scheduling assistance with confirmation tracking, referral aging with no-show follow-up, consult note return with loop-closure verification, prior-authorization flagging, referral-to-visit conversion reporting, and leakage analytics attributed back to the referring provider. The audience is the engineering team building the service; the voice throughout is that of the product owner describing behavior, not implementation. Every rule in this document is normative.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. If either header is missing, or if the value of `X-User-Role` is not one of the declared role strings, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 401). If the role is valid but not permitted for the invoked endpoint, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Five roles exist, spelled exactly as follows: `NetworkAdmin`, `ReferralCoordinator`, `ReferringProvider`, `SpecialistProvider`, `ComplianceAuditor`.

Two roles are entity-backed. When `X-User-Role` is `ReferringProvider`, `X-User-ID` is the `id` of the acting `ReferringProvider`; ownership checks on any resource that references a `ReferringProvider` compare the resource's foreign-key field to `X-User-ID`. In particular, a `ReferringProvider` may only read, resubmit, or cancel referrals whose `referring_provider_id` equals their `X-User-ID`, and may only read their own leakage records, snapshots, and leakage report; violating this scoping yields `ERR_OWNERSHIP_VIOLATION` (HTTP 403). When `X-User-Role` is `SpecialistProvider`, `X-User-ID` is the `id` of the acting `SpecialistProvider`; completing an appointment or submitting a consult note requires the appointment's `specialist_id` to equal `X-User-ID`, with `ERR_OWNERSHIP_VIOLATION` (HTTP 403) on mismatch.

The remaining three roles are opaque. When `X-User-Role` is `ReferralCoordinator`, `ComplianceAuditor`, or `NetworkAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `scheduled_by_user_id` on an `Appointment` when a coordinator books it, or as `verifier_user_id` on a `LoopClosure` when an auditor verifies one — but it does not compare it to any entity's `id` for ownership purposes.

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

List endpoints accept two optional query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0. List responses are sorted by `created_at` ascending. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`, so a client can page deterministically through the full result set.

### 2.4. Common Resource Properties and the Logical Clock

Most persisted resources carry four system-maintained properties: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recorded at creation; `updated_at`, an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation; and `version`, an integer starting at 1 that increments by exactly 1 on every mutation of that resource. Three resource kinds are exceptions: `ConsultNote`, `LoopClosure`, and `LeakageRecord` carry only `id` and `created_at` — both `updated_at` and `version` are absent on those three, and nothing about them is ever mutated after creation. `ProviderPeriodSnapshot` likewise carries no `updated_at` and no `version`; it is a frozen row created at period close.

All time in the system flows through a single logical clock rather than the host wall clock. At startup the clock reads exactly `2026-08-01T00:00:00Z`; it stays there until advanced. A `NetworkAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. Everywhere this document says "now" or "current date", it means this logical clock, never wall-clock time; before any clock-set call, every temporal rule evaluates against the startup default.

### 2.5. Optimistic Concurrency Control

Two write operations guard against stale reads via optimistic concurrency control on the parent `Referral`. Booking an appointment for a referral requires the request to carry `expected_referral_version`, a non-optional input field holding the client last observed `version` of that referral. Because a successful booking legitimately supersedes any still-active appointment of the same referral — auto-cancelling it — a writer holding a stale view of the referral must re-read before booking: if the supplied value does not equal the referral's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is written. Verifying or reopening loop closure on a referral carries the same requirement: the request must carry `expected_referral_version` matching the referral's current `version`, because the clinical state under review may have changed since the auditor's read, and a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named here do not take any version field.

### 2.6. Precision, Rounding, and Time Arithmetic

Timestamps are compared to the second; date-window arithmetic is exact to the second. Money is always integer cents: every estimated leakage line value is rounded half-up to zero decimal places at the moment the line is created and then frozen; period exposure sums add already-rounded integers and never re-round. Rates (conversion and leakage) are computed to 4 decimal places with round-half-up; a rate whose denominator is zero is reported as exactly 0.0000. No-show risk scores are capped at 100; the forward-looking variant moves in half-point steps of 12.5 granularity in practice, since the per-appointment overdue weight is 0.5. Utilization comparisons are exact rational comparisons of booked count to weekly capacity — no rounding is applied before the threshold test.

### 2.7. Validation Priority Order

When several checks could reject the same request, they are evaluated in a fixed priority order so the surfaced error is deterministic. First, presence and validity of the two user-context headers (priority 1, `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, whether the role is permitted on the endpoint (priority 2, `ERR_UNAUTHORIZED_ROLE`). Third, ownership scoping for entity-backed roles (priority 3, `ERR_OWNERSHIP_VIOLATION`). Fourth, request shape — required fields present, types valid, enum members valid, datetime and date formats well-formed (priority 4, `ERR_INVALID_REQUEST`). Fifth, existence: path resource ids are validated left to right, then body foreign-key references in their declared input order (priority 5 — the 404 family such as `ERR_REFERRAL_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_SPECIALIST_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_PARTICIPATION_NOT_FOUND`, `ERR_AUTH_RULE_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_CONSULT_NOTE_NOT_FOUND`). Sixth, the optimistic-concurrency check on `expected_referral_version` where the endpoint requires it (priority 6, `ERR_STALE_VERSION`) — this check runs after existence and before any state or business rule, so a stale version surfaces even when the transition would also be invalid. Seventh, state preconditions of the invoked transition (priority 7 — `ERR_INVALID_STATE`, `ERR_NOT_CONFIRMED`, `ERR_AUTH_NOT_SATISFIED`). Eighth, business-safety rules: suspended referring provider, retired plan, segregation of duties (priority 8 — `ERR_PROVIDER_SUSPENDED` and `ERR_SOD_CONFLICT` at 403, `ERR_PLAN_RETIRED` at 409). Ninth, specialty and target consistency on assignment and booking (priority 9 — `ERR_SPECIALTY_MISMATCH`, `ERR_TARGET_MISMATCH`, both 422). Tenth, uniqueness and selector-pool rules (priority 10 — `ERR_DUPLICATE_MRN`, `ERR_DUPLICATE_NPI`, `ERR_DUPLICATE_PLAN_CODE`, `ERR_DUPLICATE_AUTH_RULE` at 409; `ERR_NO_ELIGIBLE_SPECIALIST` at 422). Eleventh, temporal rules (priority 11 — `ERR_INVALID_WINDOW` and `ERR_INVALID_PERIOD` at 400; `ERR_PARTICIPATION_WINDOW_OVERLAP`, `ERR_APPOINTMENT_OVERLAP`, `ERR_PERIOD_NOT_ENDED`, `ERR_PERIOD_ALREADY_CLOSED` at 409; `ERR_NO_SHOW_TOO_EARLY` and `ERR_COMPLETE_TOO_EARLY` at 422). Within that final temporal priority, window-shape errors are reported before overlap errors, and overlap errors before threshold or grace errors.

## 3. Business Logic & Workflows

### 3.1. Building the Network: Providers, Plans, Participation, and Auth Rules

A `NetworkAdmin` provisions the roster before any referral can flow. Creating a referring provider takes `name`, `npi`, and a free-text primary `specialty`; creating a specialist takes `name`, `npi`, a `specialty` drawn from exactly `CARDIOLOGY`, `ORTHOPEDICS`, `NEUROLOGY`, `DERMATOLOGY`, or `ENDOCRINOLOGY`, a `base_region` service tag, an integer `weekly_capacity` of at least 1, and optionally `accepts_new_patients` (defaulting to true) and `accepts_urgent` (defaulting to false). The National Provider Identifier is unique across both provider kinds: a second registration of the same `npi` on either a referring provider or a specialist fails with `ERR_DUPLICATE_NPI`. Both provider kinds start in `ACTIVE` status; a `NetworkAdmin` may suspend a provider, moving it to `SUSPENDED`, and later reactivate it back to `ACTIVE` — each such action requires the matching current state and otherwise fails with `ERR_INVALID_STATE`. A suspended specialist becomes ineligible for matching and booking; a suspended referring provider is blocked from creating new referrals with `ERR_PROVIDER_SUSPENDED`. Every specialist also carries a computed `booked_appointments_count`, initialized to zero, tracking how many of that specialist's appointments currently sit in `SCHEDULED` or `CONFIRMED` status; the counter is maintained on every booking, cancellation, no-show, completion, and supersede.

Insurance plans are registered with a unique `plan_code` (duplicates fail with `ERR_DUPLICATE_PLAN_CODE`), a display `payer_name`, and a `payer_mix_factor` reimbursement multiplier that must be greater than zero. A plan begins `ACTIVE`; retiring it flips `status` to `RETIRED`, after which creating referrals, participation rows, or prior-auth rules against that plan is rejected with `ERR_PLAN_RETIRED` — existing rows are unaffected.

Network participation joins specialists to plans. A participation row records `specialist_id`, `insurance_plan_id`, a `tier` of either `PREFERRED` or `STANDARD`, and an inclusive date window from `effective_from` through `effective_to`; the window is malformed when `effective_to` falls before `effective_from`, which fails with `ERR_INVALID_WINDOW`. A new `ACTIVE` participation row may not overlap an existing `ACTIVE` row for the same specialist-and-plan pair — overlap is judged with inclusive date arithmetic, so two windows that share even a single calendar day collide with `ERR_PARTICIPATION_WINDOW_OVERLAP`, while pure adjacency, where the next window starts exactly one day after the previous window ends, is allowed. Terminating a row flips it to `TERMINATED` and excludes it from overlap checks and from the booking gate thereafter.

Prior-authorization policy is expressed as `PriorAuthRule` rows keyed by a `specialty` and an `insurance_plan_id`, carrying `requires_auth` and an integer `auth_validity_days` of at least 1. At most one `ACTIVE` rule may exist per specialty-and-plan pair; creating a second `ACTIVE` row for the same pair fails with `ERR_DUPLICATE_AUTH_RULE`. Retiring a rule frees the pair's uniqueness slot so a replacement rule can be created.

### 3.2. Patient Registration and No-Show Risk Posture

Patients are registered by a `NetworkAdmin` with a unique `mrn` (duplicates fail with `ERR_DUPLICATE_MRN`), `full_name`, `date_of_birth` as an ISO `YYYY-MM-DD` date, a `region` tag, and an `insurance_plan_id` naming the patient's default plan.

Each patient carries a computed strike ledger and a two-variant risk score. The `no_show_strikes` counter is the count of that patient's appointments currently in `NO_SHOW` status — appointments later excused out of `NO_SHOW` stop counting. The posture threshold is a strike limit of 3: when `no_show_strikes` rises to at least 3 the patient's `status` flips from `ACTIVE` to `OUTREACH_REQUIRED`, and when it falls back below 3 the patient returns to `ACTIVE`. The boundary is inclusive on the way up — exactly 3 strikes triggers outreach — and the downward crossing back below 3 is what clears it.

Two risk scores are exposed on every patient read. The confirmed-only variant, `no_show_risk_confirmed`, is the strike weight of 25 multiplied by the current strike count, capped at 100. The forward-looking variant, `no_show_risk_forward`, additionally counts overdue unconfirmed appointments: any appointment of the patient still in `SCHEDULED` status whose scheduled start plus 24 hours is at or before now contributes a weight of 0.5 each, so the score is the strike weight of 25 multiplied by the sum of the strike count plus half the overdue count, again capped at 100. The 24-hour boundary is inclusive — an appointment exactly 24 hours past its scheduled start counts as overdue. Because each overdue appointment adds half a strike-weight's share, the forward score exceeds the confirmed score whenever such appointments exist, and it can take half-integer values before the cap. Both scores are recomputed whenever the patient is read and after any mark-no-show, excuse, or confirmation-state change affecting the overdue set.

### 3.3. Referral Intake and Triage

A `ReferringProvider` creates a referral order by posting the `patient_id`, the target `specialty` (one of the five enumerated specialties), a free-text `diagnosis_code`, an `urgency` of `STAT`, `URGENT`, or `ROUTINE`, optionally an `insurance_plan_id` (defaulting to the patient's own plan when omitted), and optionally an `in_network_preference` flag (defaulting to true) documenting the patient's stated network preference. The `referring_provider_id` is never accepted from the payload — it is set from the caller's `X-User-ID`, so a provider can only author referrals under their own identity. A new referral begins in `PENDING_TRIAGE` status with `auth_status` set to `NOT_EVALUATED`. If the referring provider has been suspended, creation fails with `ERR_PROVIDER_SUSPENDED`; if the referenced plan is retired, creation fails with `ERR_PLAN_RETIRED`.

From `PENDING_TRIAGE`, a `ReferralCoordinator` has three paths. Requesting information moves the referral to `NEEDS_INFO` and stores the coordinator's note in `needs_info_note`; only a referral currently in `PENDING_TRIAGE` can be sent back this way, otherwise `ERR_INVALID_STATE`. Rejecting moves it to the terminal `REJECTED` state, also only from `PENDING_TRIAGE`. Accepting moves it to `ACCEPTED` and performs three bookkeeping steps: `triaged_at` is stamped with the current clock; `sla_due_at` is computed as `triaged_at` plus the urgency's service-level window — 2 days for `STAT`, 7 days for `URGENT`, 30 days for `ROUTINE`, using exact second arithmetic; and the prior-auth dimension is evaluated (see §3.4).

A referral sitting in `NEEDS_INFO` can be resubmitted, but only by the owning referring provider — a different provider's `X-User-ID` fails with `ERR_OWNERSHIP_VIOLATION`. Resubmission returns the referral to `PENDING_TRIAGE` and applies whichever of the optional updates were supplied: a revised `diagnosis_code`, a revised `urgency`, a revised `in_network_preference`, or a revised `insurance_plan_id`. Fields not supplied remain as they were.

Every referral read exposes `age_days`, the whole number of calendar days between `created_at` and now, computed as the floor of the elapsed seconds divided by 86,400 and evaluated fresh at read time in UTC.

### 3.4. Prior Authorization as a Parallel Dimension

The referral's `auth_status` evolves on its own track, independently of the main status, and begins at `NOT_EVALUATED`. During the accept transition the system looks for an `ACTIVE` prior-auth rule matching the referral's `specialty` and `insurance_plan_id` with `requires_auth` true. If such a rule exists, `auth_status` becomes `AUTH_REQUIRED`; otherwise it becomes `NOT_REQUIRED`.

From `AUTH_REQUIRED` — and equally from `AUTH_DENIED` or `AUTH_EXPIRED` — a `ReferralCoordinator` may submit the case to the payer, moving `auth_status` to `AUTH_PENDING`. Submission is only valid while the referral's main status is `ACCEPTED` or `SCHEDULED`; invoking it from any other combination fails with `ERR_INVALID_STATE`. When the payer's decision comes back, the coordinator records the outcome. Recording `OBTAINED` requires a non-empty `auth_number` in the payload — its absence fails with `ERR_INVALID_REQUEST` — and creates an `AuthorizationRecord` stamped with the `referral_id` of the referral it belongs to, the `auth_number`, an `obtained_at` of the current clock, and an `expires_on` computed as `obtained_at` plus the matching rule's `auth_validity_days` using exact second arithmetic; the record starts `ACTIVE` and the referral's `auth_status` becomes `AUTH_OBTAINED`. Recording `DENIED` moves `auth_status` to `AUTH_DENIED` and creates no record. Either recording requires the referral to currently sit in `AUTH_PENDING`, else `ERR_INVALID_STATE`.

Authorizations age out through the aging sweep: when a referral is in `AUTH_OBTAINED` with main status `ACCEPTED` or `SCHEDULED`, and its latest `AuthorizationRecord` is still `ACTIVE`, and now has reached or passed that record's `expires_on` — the boundary is inclusive — the record flips to `EXPIRED` and the referral's `auth_status` becomes `AUTH_EXPIRED`, from which a fresh submission can restart the cycle. When a visit ultimately completes on a referral in `AUTH_OBTAINED`, the latest authorization record is marked `CONSUMED`, closing it out.

### 3.5. Specialist Matching and Assignment

Matching a referral to a specialist can happen two ways. Automatic matching runs a weighted ranking over the whole specialist roster. A candidate must satisfy five eligibility conditions to enter the pool at all: the specialist's `specialty` equals the referral's `specialty`; the specialist's `status` is `ACTIVE`; `accepts_new_patients` is true; for a `STAT`-urgency referral `accepts_urgent` must also be true; and an `ACTIVE` participation row must exist joining that specialist to the referral's `insurance_plan_id` with a window covering the current date — `effective_from` on or before today and `effective_to` on or after today, both bounds inclusive. Every eligible candidate receives an integer score. The score starts at a base of 50. A candidate whose matching participation `tier` is `PREFERRED` gains 25 points; a `STANDARD` tier gains 10 instead. A candidate whose panel utilization — the ratio of `booked_appointments_count` to `weekly_capacity`, compared as an exact rational — has reached at least 0.8 loses 15 points; the threshold is inclusive, so a panel at exactly 0.8 utilization takes the penalty. Urgency adds 20 points for a `STAT` referral, 10 for `URGENT`, and nothing for `ROUTINE`. A specialist whose `base_region` matches the patient's `region` (compared case-sensitively) gains 5 points. The total is then clamped to lie between 0 and 100 inclusive.

The winner is the candidate with the highest score; ties break in favor of the specialist whose `created_at` is earliest. On success the referral's `target_specialist_id` is set to the winner and `match_score` records the winning score. If the eligibility filter empties the pool, the call fails with `ERR_NO_ELIGIBLE_SPECIALIST` (HTTP 422) and the referral is left unchanged.

Manual assignment is the alternative: a `ReferralCoordinator` supplies a `specialist_id`, and the system sets `target_specialist_id` to it while leaving `match_score` null. The same consistency rules apply as at booking — the specialist must exist (`ERR_SPECIALIST_NOT_FOUND`), must be `ACTIVE` and accepting new patients, and must share the referral's `specialty` or the request fails with `ERR_SPECIALTY_MISMATCH`.

While a referral is `ACCEPTED`, the coordinator may also document the patient's choice. Recording a choice sets `patient_choice_documented` to true and stores a `patient_choice_type` of `IN_NETWORK_PREFERRED`, `OUT_OF_NETWORK_PATIENT_REQUEST`, or `OUT_OF_NETWORK_CAPACITY` (the initial value before documentation is `NONE`) together with a free-text `patient_choice_note`; the two inputs are `choice_type` and `note`. This documentation is what later legitimizes an out-of-network booking.

### 3.6. Booking, Supersede, and the Visit Lifecycle

Booking an appointment is the referral center's core scheduling-assistance act, and it is guarded by the optimistic-concurrency rule of §2.5: the request must carry `expected_referral_version` equal to the referral's current `version`, else `ERR_STALE_VERSION` (HTTP 412). The booking request also carries `scheduled_start` and `scheduled_end` as ISO 8601 UTC timestamps and may optionally name a `specialist_id`. A fresh booking requires the referral to be `ACCEPTED`; a superseding booking is allowed while the referral is `SCHEDULED`; from any other status the attempt fails with `ERR_INVALID_STATE`.

Five gates then apply, in this order of concern. Authorization first: the referral's `auth_status` must be `NOT_REQUIRED`, or `AUTH_OBTAINED` with the latest `AuthorizationRecord` still `ACTIVE`; booking against `AUTH_REQUIRED`, `AUTH_PENDING`, `AUTH_DENIED`, or `AUTH_EXPIRED` — or against an obtained authorization whose record has lapsed — fails with `ERR_AUTH_NOT_SATISFIED`. Specialist validity second: the effective specialist — the payload's `specialist_id` when supplied, otherwise the referral's `target_specialist_id` — must exist (`ERR_SPECIALIST_NOT_FOUND`), be `ACTIVE`, accept new patients, and share the referral's `specialty` (`ERR_SPECIALTY_MISMATCH`). Target fidelity third: when a `target_specialist_id` is set and the payload names a different specialist, the request fails with `ERR_TARGET_MISMATCH`. Network participation fourth: an `ACTIVE` participation row must cover the specialist and the referral's plan on the current date; when none exists, booking still proceeds only if `patient_choice_documented` is true and `patient_choice_type` is `OUT_OF_NETWORK_PATIENT_REQUEST` or `OUT_OF_NETWORK_CAPACITY`, and otherwise fails with `ERR_NO_ACTIVE_PARTICIPATION`. Overlap fifth: the new appointment's occupied interval — from its start to its end plus a 15-minute buffer, half-open — must not intersect any other `SCHEDULED` or `CONFIRMED` appointment of the same specialist, whose occupied intervals use the same start to end-plus-15-minutes half-open shape; a new appointment starting at or after an existing appointment's end plus 15 minutes is fine, but any genuine intersection fails with `ERR_APPOINTMENT_OVERLAP`. Separately, the window itself must be well-formed: `scheduled_end` strictly after `scheduled_start`, and `scheduled_start` not in the past relative to the current clock — violations fail with `ERR_INVALID_WINDOW`.

A successful booking performs several writes as one atomic act. If the referral already has an appointment in `SCHEDULED` or `CONFIRMED`, that appointment transitions to `CANCELLED` with `superseded` set to true and its specialist's `booked_appointments_count` decremented by 1. The new `Appointment` is created in `SCHEDULED` status with `scheduled_by_user_id` recorded from the caller's `X-User-ID`, and the effective specialist's `booked_appointments_count` increments by 1. The referral moves to `SCHEDULED`, its `ever_scheduled` flag is set true — it is never cleared afterward — and its `version` increments. When the participation gate was bypassed on the strength of a documented out-of-network choice, the booking additionally marks the referral `out_of_network` true and creates a `LeakageRecord`: its `category` is `PATIENT_CHOICE_OUT_OF_NETWORK` when the documented choice type was `OUT_OF_NETWORK_PATIENT_REQUEST`, and `CAPACITY_OUT_OF_NETWORK` when it was `OUT_OF_NETWORK_CAPACITY`; the referral's `leaked` flag turns true; and the attributed referring provider's `leakage_event_count` increments by 1 with the provider's `watch_flag` recomputed (see §3.8).

Once booked, an appointment can be confirmed: a `ReferralCoordinator` records the `confirmation_channel` — exactly one of `PHONE`, `PORTAL`, or `LETTER` — and the system stamps `confirmed_at` with the current clock; only a `SCHEDULED` appointment can be confirmed, otherwise `ERR_INVALID_STATE`. Confirmation is the closed-loop check that the patient was actually reached.

Completion belongs to the specialist. The acting specialist must be the appointment's owner — the appointment's `specialist_id` compared to `X-User-ID`, else `ERR_OWNERSHIP_VIOLATION` — and the appointment must be `CONFIRMED`, else `ERR_NOT_CONFIRMED`. Completion before the appointment's scheduled start is rejected with `ERR_COMPLETE_TOO_EARLY`. A successful completion stamps `completed_at`, decrements the specialist's `booked_appointments_count` by 1, advances the referral from `SCHEDULED` to `VISIT_COMPLETED`, and — when the referral's `auth_status` is `AUTH_OBTAINED` — marks the latest authorization record `CONSUMED`.

When the patient does not appear, a `ReferralCoordinator` marks the appointment no-show. This is allowed from either `SCHEDULED` or `CONFIRMED`, but only once now has reached the scheduled start plus a 15-minute grace — attempting it earlier fails with `ERR_NO_SHOW_TOO_EARLY`, and the boundary is inclusive, so exactly start-plus-15-minutes is allowed. Marking no-show sets the appointment to `NO_SHOW`, decrements the specialist's `booked_appointments_count` by 1, and fires a three-link patient cascade: first, the patient's `no_show_strikes` increments by 1; second, if the increment lifts the count to at least the strike limit of 3, the patient's `status` flips to `OUTREACH_REQUIRED`; third, on that flip, every referral of that patient currently in `ACCEPTED` or `SCHEDULED` has its `escalation_flag` set true. Finally, if no sibling appointment of the referral remains in `SCHEDULED` or `CONFIRMED`, the referral falls back from `SCHEDULED` to `ACCEPTED`, ready to be rebooked. This last revert is the same system transition that fires whenever the last active appointment of a `SCHEDULED` referral becomes terminal through cancellation or excuse with no active sibling remaining.

An erroneous no-show can be compensated: excusing a `NO_SHOW` appointment (from no other status, else `ERR_INVALID_STATE`) stores the supplied `reason` in `excuse_reason`, moves the appointment to `EXCUSED`, decrements the patient's `no_show_strikes` by 1, and when the count thereby falls below 3 while the patient is `OUTREACH_REQUIRED`, returns the patient to `ACTIVE` and clears `escalation_flag` on every referral of that patient where it had been set.

A coordinator may also cancel an appointment outright from `SCHEDULED` or `CONFIRMED` (else `ERR_INVALID_STATE`), which frees the booked slot by decrementing `booked_appointments_count` and, when the cancellation was a direct one — not a supersede, not a referral-level cascade — and no sibling appointment remains active and the referral still reads `SCHEDULED`, returns the referral to `ACCEPTED`. Cancellation from the referral side works at the referral level: either the owning `ReferringProvider` or any `ReferralCoordinator` may cancel a referral that is not yet terminal — `PENDING_TRIAGE`, `NEEDS_INFO`, `ACCEPTED`, `SCHEDULED`, `VISIT_COMPLETED`, or `PENDING_VERIFICATION` are all cancellable, anything else fails with `ERR_INVALID_STATE`, and a referring provider attempting to cancel someone else's referral fails with `ERR_OWNERSHIP_VIOLATION`. The supplied `reason` — one of `PATIENT_WENT_OUT_OF_NETWORK`, `PATIENT_DECLINED`, `CLINICAL_DUPLICATE`, or `OTHER` — is stored in `cancel_reason`. Any appointment of the referral still in `SCHEDULED` or `CONFIRMED` is cascade-cancelled and its slot freed. When the reason is `PATIENT_WENT_OUT_OF_NETWORK` and the referral has not already leaked, the cancellation additionally creates a `LeakageRecord` of category `PATIENT_CHOICE_OUT_OF_NETWORK`, sets `leaked` true, and increments the attributed provider's `leakage_event_count` with `watch_flag` recomputed.

### 3.7. Consult Note Return and Loop Closure Verification

After the visit completes, the clinical loop closes in two steps. The owning specialist submits a consult note against the completed appointment, supplying `findings_summary` free text and a `follow_up_recommended` boolean; ownership is enforced exactly as at completion (`ERR_OWNERSHIP_VIOLATION`). Each note is stamped with the `appointment_id` it was filed under and the `referral_id` reached through that appointment. The note's `note_sequence` is assigned as 1 plus the count of prior consult notes on the same referral, so the first note on a referral is sequence 1; its `author_specialist_id` is set from the caller's `X-User-ID`; and `returned_within_sla` is computed by comparing the note's `created_at` against the appointment's `completed_at` plus a 14-day return window — at or before that deadline counts as within SLA. Submitting the note advances the referral from `VISIT_COMPLETED` to `PENDING_VERIFICATION` and increments the referral's `version`.

Verification belongs to an independent `ComplianceAuditor`, and it is the system's segregation-of-duties keystone: the auditor's `X-User-ID` must differ from the `scheduled_by_user_id` of the referral's latest `COMPLETED` appointment — the person who scheduled the visit may not verify its closure, and a match fails with `ERR_SOD_CONFLICT` (HTTP 403). The verification request also carries the OCC guard of §2.5 — `expected_referral_version` equal to the referral's current `version`, else `ERR_STALE_VERSION` — and requires the referral to actually sit in `PENDING_VERIFICATION`, else `ERR_INVALID_STATE`. The auditor posts an `outcome` of `VERIFIED_CLOSED` or `REOPENED` together with a `verification_note`. A `LoopClosure` record is created with its `referral_id` and `verifier_user_id` taken from the request context — the former naming the referral under review, the latter the caller's `X-User-ID`. On `VERIFIED_CLOSED` the referral reaches its terminal `CLOSED` state; on `REOPENED` it drops back to `VISIT_COMPLETED`, awaiting another note and another verification pass. Either outcome increments the referral's `version`.

### 3.8. Aging, Leakage Attribution, and Analytics

An ops-run aging sweep is the system's housekeeping pass, runnable by a `ReferralCoordinator`. It walks qualifying referrals in `created_at` ascending order and expires any referral whose status is `ACCEPTED`, `SCHEDULED`, `VISIT_COMPLETED`, or `PENDING_VERIFICATION` and whose `sla_due_at` has been reached — the boundary is inclusive, so a referral exactly at its deadline expires. Expiry moves the referral to `EXPIRED`, creates a `LeakageRecord` of category `EXPIRED_UNRESOLVED`, sets `leaked` true, increments the attributed provider's `leakage_event_count` with `watch_flag` recomputed, cascade-cancels any appointment still in `SCHEDULED` or `CONFIRMED` (freeing the slot), and bumps the referral's `version`. The same sweep also ages authorizations per §3.4, flipping stale records to `EXPIRED` and their referrals to `AUTH_EXPIRED`. The sweep reports back the expired referral ids, how many referrals expired, and the expired authorization record ids.

Leakage is the analytic heart of the product. Every `LeakageRecord` carries its `category` — `EXPIRED_UNRESOLVED`, `PATIENT_CHOICE_OUT_OF_NETWORK`, or `CAPACITY_OUT_OF_NETWORK` — and an `attributed_referring_provider_id` copied from the referral at creation. Its `estimated_value_cents` is frozen at creation as the specialty's base value multiplied by the referral plan's `payer_mix_factor`, rounded half-up to whole cents. The per-specialty base values, in cents, are: 42,000 for `CARDIOLOGY`; 33,500 for `ORTHOPEDICS`; 50,000 for `NEUROLOGY`; 18,000 for `DERMATOLOGY`; 26,000 for `ENDOCRINOLOGY`. On the provider side, each created record increments `leakage_event_count`; once that count reaches the watch threshold of 2 — inclusively — the provider's `watch_flag` becomes true, and it never auto-clears, since no decrement path exists.

Two conversion-rate bases coexist because they answer different questions. The intake basis divides the count of completed referrals by the full intake set — the provider's referrals created within the window whose status is not `REJECTED`, statuses being evaluated at computation time. The scheduled basis divides the same completed count by the subset of the intake set whose `ever_scheduled` flag is true; because its denominator only shrinks, the scheduled-basis rate is always at least the intake-basis rate for identical data, and strictly greater whenever any intake referral never reached scheduling. A referral counts as completed for these purposes when at least one of its appointments has reached `COMPLETED`. Both rates are reported to 4 decimal places, round-half-up, and a zero denominator yields 0.0000. The leakage rate is the count of intake referrals with `leaked` true divided by the intake count, on the same 4-decimal rounding and zero-denominator convention.

A live analytics read is available per referring provider. It computes over an all-time window rather than a bound period, accepts an optional `basis` selector choosing the intake or scheduled conversion basis, and returns the chosen `basis` label, `intake_count`, `completed_count`, `leaked_count`, the selected `conversion_rate`, the `leakage_rate`, and `estimated_leakage_exposure_cents`. A `ReferringProvider` caller may only read their own id (`ERR_OWNERSHIP_VIOLATION`).

Period close is the snapshot counterpart, run by a `NetworkAdmin` with a `period_start` (inclusive) and `period_end` (exclusive) — the window covers referrals whose `created_at` is at or after `period_start` and strictly before `period_end`. Three preconditions guard it: `period_end` must be strictly after `period_start`, else `ERR_INVALID_PERIOD`; the current date must have reached `period_end`, else `ERR_PERIOD_NOT_ENDED`; and no snapshot may already exist for the same period pair, else `ERR_PERIOD_ALREADY_CLOSED`. The close walks referring providers in `created_at` ascending order and, for each whose intake set in the window is non-empty, writes one `ProviderPeriodSnapshot` pinned at close time. Each snapshot records `referring_provider_id`, `period_start`, `period_end`, `intake_count`, `completed_count`, `scheduled_basis_count`, `leaked_count`, `conversion_rate_intake`, `conversion_rate_scheduled`, `leakage_rate`, and `estimated_leakage_exposure_cents`, plus the `closed_at` clock timestamp. The exposure field sums the per-line `estimated_value_cents` of the leakage records attached to the intake set's leaked referrals — and the rounding order is pinned: each line is rounded to whole cents at its own creation, then the integers are summed; summing raw products and rounding once at the end is a different number and is not the implemented order.

## 4. Endpoint Definitions

All endpoints return the envelope of §2.2. Resource-creating operations respond with HTTP 201 and the created resource; modifications, actions, and reads respond with HTTP 200. Authentication, authorization, ownership, shape, existence, concurrency, state, and business-rule rejections follow §2.7's priority order.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Advance the logical clock to a supplied instant | NetworkAdmin |
| POST | /referring-providers | Create a referring provider | NetworkAdmin |
| GET | /referring-providers | List referring providers | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider, SpecialistProvider |
| GET | /referring-providers/{id} | Get one referring provider | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider, SpecialistProvider |
| POST | /referring-providers/{id}/suspend | Suspend a referring provider (blocks new referral creation) | NetworkAdmin |
| POST | /referring-providers/{id}/reactivate | Reactivate a suspended referring provider | NetworkAdmin |
| GET | /referring-providers/{id}/referrals | List referrals created by this provider | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider, SpecialistProvider |
| GET | /referring-providers/{id}/leakage-records | List leakage records attributed to this provider | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider |
| GET | /referring-providers/{id}/leakage-snapshots | List closed period snapshots for this provider | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider |
| GET | /referring-providers/{id}/leakage-report | Live all-time analytics read for this provider | NetworkAdmin, ReferralCoordinator, ReferringProvider |
| POST | /specialty-providers | Create a specialist | NetworkAdmin |
| GET | /specialty-providers | List specialists | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider, SpecialistProvider |
| GET | /specialty-providers/{id} | Get one specialist | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider, SpecialistProvider |
| POST | /specialty-providers/{id}/suspend | Suspend a specialist | NetworkAdmin |
| POST | /specialty-providers/{id}/reactivate | Reactivate a specialist | NetworkAdmin |
| GET | /specialty-providers/{id}/network-participations | List participation rows of a specialist | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider, SpecialistProvider |
| GET | /specialty-providers/{id}/appointments | List appointments of a specialist | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, SpecialistProvider |
| POST | /patients | Register a patient | NetworkAdmin |
| GET | /patients | List patients | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider, SpecialistProvider |
| GET | /patients/{id} | Get one patient (includes computed strikes/risk fields) | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider, SpecialistProvider |
| GET | /patients/{id}/referrals | List referrals of a patient | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider, SpecialistProvider |
| POST | /insurance-plans | Create an insurance plan | NetworkAdmin |
| GET | /insurance-plans | List insurance plans | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider, SpecialistProvider |
| GET | /insurance-plans/{id} | Get one insurance plan | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider, SpecialistProvider |
| POST | /insurance-plans/{id}/retire | Retire a plan | NetworkAdmin |
| POST | /network-participations | Create a participation window | NetworkAdmin |
| GET | /network-participations | List participation rows | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider, SpecialistProvider |
| GET | /network-participations/{id} | Get one participation row | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider, SpecialistProvider |
| POST | /network-participations/{id}/terminate | Terminate a participation row | NetworkAdmin |
| POST | /prior-auth-rules | Create a prior-auth rule | NetworkAdmin |
| GET | /prior-auth-rules | List prior-auth rules | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider, SpecialistProvider |
| GET | /prior-auth-rules/{id} | Get one prior-auth rule | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider, SpecialistProvider |
| POST | /prior-auth-rules/{id}/retire | Retire a prior-auth rule | NetworkAdmin |
| POST | /referrals | Create a referral order | ReferringProvider |
| GET | /referrals | List referrals; ReferringProvider role sees only own referrals | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider, SpecialistProvider |
| GET | /referrals/{id} | Get one referral | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider, SpecialistProvider |
| POST | /referrals/{id}/request-info | Coordinator requests clarification | ReferralCoordinator |
| POST | /referrals/{id}/resubmit | Owning provider resubmits a NEEDS_INFO referral | ReferringProvider |
| POST | /referrals/{id}/reject | Coordinator rejects a PENDING_TRIAGE referral | ReferralCoordinator |
| POST | /referrals/{id}/accept | Coordinator accepts a PENDING_TRIAGE referral | ReferralCoordinator |
| POST | /referrals/{id}/auto-match | Run the specialty-match ranking and set the target specialist | ReferralCoordinator |
| POST | /referrals/{id}/assign-specialist | Manually set the target specialist | ReferralCoordinator |
| POST | /referrals/{id}/document-patient-choice | Document patient choice while ACCEPTED | ReferralCoordinator |
| POST | /referrals/{id}/cancel | Cancel a non-terminal referral | ReferringProvider, ReferralCoordinator |
| POST | /referrals/{id}/auth/submit | Initiate prior authorization | ReferralCoordinator |
| POST | /referrals/{id}/auth/record-outcome | Record payer decision | ReferralCoordinator |
| POST | /referrals/{id}/appointments | Book an appointment (OCC-guarded; supersedes any active appointment) | ReferralCoordinator |
| GET | /referrals/{id}/appointments | List appointments of a referral | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider, SpecialistProvider |
| GET | /referrals/{id}/authorization-records | List authorization records of a referral | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider, SpecialistProvider |
| GET | /referrals/{id}/consult-notes | List consult notes of a referral | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider, SpecialistProvider |
| GET | /referrals/{id}/loop-closures | List loop-closure records of a referral | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider, SpecialistProvider |
| GET | /referrals/{id}/leakage-records | List leakage records of a referral | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider |
| POST | /referrals/{id}/loop-closures | Verify or reopen loop closure (OCC-guarded; SoD-enforced) | ComplianceAuditor |
| POST | /referrals/aging-sweep | Expire referrals past SLA and stale authorization records | ReferralCoordinator |
| GET | /appointments/{id} | Get one appointment | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider, SpecialistProvider |
| POST | /appointments/{id}/confirm | Record closed-loop confirmation | ReferralCoordinator |
| POST | /appointments/{id}/complete | Mark visit completed (owning specialist only) | SpecialistProvider |
| POST | /appointments/{id}/mark-no-show | Mark no-show after the grace period | ReferralCoordinator |
| POST | /appointments/{id}/excuse | Excuse a NO_SHOW appointment | ReferralCoordinator |
| POST | /appointments/{id}/cancel | Cancel an active appointment | ReferralCoordinator |
| POST | /appointments/{id}/consult-note | Submit consult note for a COMPLETED appointment | SpecialistProvider |
| GET | /appointments/{id}/consult-notes | List consult notes of an appointment | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider, SpecialistProvider |
| GET | /consult-notes | List consult notes (filtered) | NetworkAdmin, ReferralCoordinator, ComplianceAuditor |
| GET | /consult-notes/{id} | Get one consult note | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider, SpecialistProvider |
| POST | /analytics/periods/close | Close an analytics period and write provider snapshots | NetworkAdmin |
| GET | /analytics/snapshots | List closed period snapshots | NetworkAdmin, ReferralCoordinator, ComplianceAuditor, ReferringProvider |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_OWNERSHIP_VIOLATION | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_REFERRAL_NOT_FOUND | 404 |
| ERR_PATIENT_NOT_FOUND | 404 |
| ERR_SPECIALIST_NOT_FOUND | 404 |
| ERR_PLAN_NOT_FOUND | 404 |
| ERR_PARTICIPATION_NOT_FOUND | 404 |
| ERR_AUTH_RULE_NOT_FOUND | 404 |
| ERR_APPOINTMENT_NOT_FOUND | 404 |
| ERR_PROVIDER_NOT_FOUND | 404 |
| ERR_CONSULT_NOTE_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_NOT_CONFIRMED | 409 |
| ERR_AUTH_NOT_SATISFIED | 409 |
| ERR_PROVIDER_SUSPENDED | 403 |
| ERR_PLAN_RETIRED | 409 |
| ERR_SOD_CONFLICT | 403 |
| ERR_SPECIALTY_MISMATCH | 422 |
| ERR_TARGET_MISMATCH | 422 |
| ERR_DUPLICATE_MRN | 409 |
| ERR_DUPLICATE_NPI | 409 |
| ERR_DUPLICATE_PLAN_CODE | 409 |
| ERR_DUPLICATE_AUTH_RULE | 409 |
| ERR_INVALID_WINDOW | 400 |
| ERR_PARTICIPATION_WINDOW_OVERLAP | 409 |
| ERR_APPOINTMENT_OVERLAP | 409 |
| ERR_NO_SHOW_TOO_EARLY | 422 |
| ERR_COMPLETE_TOO_EARLY | 422 |
| ERR_NO_ACTIVE_PARTICIPATION | 409 |
| ERR_NO_ELIGIBLE_SPECIALIST | 422 |
| ERR_INVALID_PERIOD | 400 |
| ERR_PERIOD_NOT_ENDED | 409 |
| ERR_PERIOD_ALREADY_CLOSED | 409 |

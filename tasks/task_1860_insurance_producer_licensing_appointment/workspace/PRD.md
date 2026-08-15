# Insurance Producer Licensing & Appointment Management API — Product Requirements Document

## 1. Introduction

An insurance carrier that distributes through producers carries a continuing regulatory obligation: every policy must be solicited and written by a producer who holds an active license covering the relevant line of authority in the state where the risk is written, and who is appointed by the carrier in that state. Licensing departments too often track this obligation across spreadsheets and state portals, discovering gaps only when a commission audit or a department-of-insurance inquiry surfaces them. This document specifies the API for the carrier's licensing department — the system of record for license verification and line-of-authority mapping, carrier appointment and termination filings by state, continuing-education compliance and renewal deadlines, and the monitoring of background and regulatory actions against producers and agencies.

The platform manages the full compliance lifecycle of the distribution channel. Producers may affiliate with an agency or operate independently, and individual and agency licenses exist side by side. When a licensed producer submits a first application in a state where the carrier has not yet appointed them, the platform creates a just-in-time appointment automatically and enforces the state's filing window. Commissions are calculated on tiered rates but are held whenever the underlying business was written out of compliance, released only when the gap is cured, and forfeited when it is not. Regulatory actions follow a maker-checker discipline and cascade through licenses, appointments, and commissions when confirmed; regulatory inquiries carry a response clock whose expiry suspends the producer's book. Because so much of the domain is time-driven, the platform runs on a controllable logical clock rather than wall-clock time, and every time-based transition in this document is expressed against that clock.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, conventions, and boilerplate that apply to the entire API. All resources described here are exposed under the `/api` mount, alongside a small administrative surface reserved for the logical clock.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, specifying their operational capacity. A request that is missing either header, or that names a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, every operation is restricted by role; an attempt to perform an action outside the caller's designated role is rejected with `ERR_FORBIDDEN` (HTTP 403).

Five roles are recognized. A `Producer` is a licensed insurance producer acting on their own book. A `LicensingCoordinator` is licensing-department staff who run the producer, license, appointment, continuing-education, and application workflows. A `ComplianceOfficer` owns regulatory actions, regulatory inquiries, commission holds, and reinstatements. `FinanceOps` is carrier finance and pays commissions. `CarrierAdmin` is the carrier administrator who operates the logical clock, creates agencies (a capability shared with the `LicensingCoordinator`), and reads everything.

The meaning of `X-User-ID` depends on the role presented. When `X-User-Role` is `Producer`, `X-User-ID` is the `id` of the acting Producer record, and every ownership check compares a resource's producer foreign key to that value: a Producer may submit an application only when the payload's `producer_id` equals their `X-User-ID`, may report continuing-education credits only against licenses they hold, and may read only those records whose producer link equals their `X-User-ID`. For `LicensingCoordinator`, `ComplianceOfficer`, `FinanceOps`, and `CarrierAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it on certain resources (for example, as `created_by_user_id` on a regulatory action, `reviewed_by_user_id` on a continuing-education credit, or `decided_by_user_id` on a decided action) but never compares it to any entity's `id`.

One segregation-of-duties rule cuts across the role model: confirming or dismissing a regulatory action requires the acting `X-User-ID` to differ from the action's recorded `created_by_user_id`, so no operator may single-handedly report and ratify the same action. A breach is rejected with `ERR_SOD_VIOLATION` (HTTP 403).

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every primary resource in the platform — agencies, producers, licenses, continuing-education credits, appointments, policy applications, commission entries, regulatory actions, and regulatory inquiries — carries a standard set of system-managed properties:

- **`id`** (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification.
- **`version`** (integer): a system-managed integer that increments by one with every modification to the resource.

Every mutation counts for this purpose, including system-driven cascade mutations: when one event propagates through several records (a license suspension re-holding commissions, for example), each record touched by the cascade has its own `version` incremented by one and its `updated_at` refreshed.

### 2.5. The Logical Clock and the Scheduled Compliance Sweep

The platform never consults wall-clock time. All deadlines, windows, and time-stamped transitions are evaluated against a logical clock whose startup value is exactly 2026-08-01T00:00:00Z, and the server must not fall back to wall-clock time under any circumstance. A `CarrierAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`.

Advancing the clock runs a scheduled compliance sweep over three record families. Every license still `ACTIVE` whose `expiration_date` lies strictly before the new time transitions to `EXPIRED` — a license remains `ACTIVE` through the expiration instant itself. Every just-in-time appointment still `JIT_PENDING` whose `jit_filing_deadline` lies strictly before the new time transitions to `LAPSED`. Every regulatory inquiry still `OPEN` whose `response_due_at` lies strictly before the new time transitions to `OVERDUE`, which in turn fires the producer-suspension cascade described in §3.8. The sweep uses strict comparison throughout: an entity whose deadline equals the new clock value exactly is not swept. Each swept record's `version` increments by one.

### 2.6. Licensing Subjects: Individuals, Agencies, and Subject Exclusivity

Four record types — licenses, appointments, regulatory actions, and regulatory inquiries — always name exactly one licensing subject. On each of them, precisely one of `producer_id` or `agency_id` must be set: a record naming both, or neither, is rejected with `ERR_LICENSE_SUBJECT_CONFLICT` (HTTP 422). This exclusivity is what allows the carrier to license and appoint an agency as a firm, separately from the individual producers who write under it.

Affiliation links the two levels of the hierarchy. A producer's `agency_id` records the agency they currently write under; a null `agency_id` marks an independent producer. The hierarchy matters most at the appointment gate: an appointment held by the affiliated agency can satisfy the appointment requirement for its producers (§3.5 and §3.6), and the agency uplift in the commission schedule depends on the same affiliation (§3.6). Agency-held licenses are not expected to accumulate continuing-education hours, and by convention are created with `ce_required_hours` of 0; reporting a CE credit against an agency-held license is rejected with `ERR_CE_NOT_APPLICABLE`.

### 2.7. Numeric Precision: Cents, Credit Hours, and Instants

All monetary values are integer counts of cents; no fractional cents exist anywhere in the platform. Commission amounts are rounded down to a whole cent exactly once, at the very end of the calculation, after all rates and multipliers have been applied. Regulatory fine allocations are likewise integer cents, with each allocation line rounded down before a remainder-reconciliation pass distributes the leftover cents (§3.7).

Continuing-education hours are recorded with at most one decimal place, rounded half up on input. Hour comparisons in the compliance determination are exact, and every threshold in that determination is inclusive — a producer whose hours equal a requirement exactly has met it. All datetime comparisons in the platform (renewal windows, filing deadlines, sweep tests) are made to the second.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, each against the record the client is acting on. Renewing a license requires the non-optional field `expected_license_version`, carrying the `version` of the license the client last observed. Submitting a regulatory-inquiry response requires the non-optional field `expected_inquiry_version`, carrying the `version` of the inquiry the client last observed. In both cases, if the value does not match the record's current `version` — because another write, such as a CE-credit acceptance recomputing the license's counters or a clock sweep moving the inquiry to `OVERDUE`, has legitimately advanced it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot overwrite state it has not observed. Endpoints not named here do not accept a version field at all.

### 2.9. Validation Order and Error Precedence

Requests are validated in a fixed order so that, when several problems are present, the reported failure is deterministic. Authentication comes first (missing or invalid headers, `ERR_UNAUTHENTICATED`), followed by role authorization for the endpoint (`ERR_FORBIDDEN`). For regulatory-action confirm and dismiss, the maker-checker segregation-of-duties check (`ERR_SOD_VIOLATION`) is evaluated next. Only then are path identifiers and body foreign-key references (`producer_id`, `agency_id`, `license_id`, `application_id`) resolved, left to right, with the first missing reference producing `ERR_NOT_FOUND` (HTTP 404); this left-to-right resolution means a request naming a non-existent producer is rejected before the system even looks at a license or application under it. For callers in the `Producer` role, ownership scoping is enforced after existence: the resource's producer link must equal the caller's `X-User-ID`, else `ERR_FORBIDDEN`.

State checks come in two tiers. Domain-specific state errors are reported first: filing a `LAPSED` just-in-time appointment yields `ERR_JIT_FILING_WINDOW_CLOSED`, and paying a commission entry that is not `PAYABLE` yields `ERR_COMMISSION_NOT_PAYABLE`. Where no domain-specific error applies and the target record simply is not in a state from which the requested transition exists — renewing a `REVOKED` or `SUSPENDED` license, closing an `OPEN` inquiry, reviewing an already-terminal CE credit — the generic rejection is `ERR_INVALID_STATE` (HTTP 409).

Business-safety gates follow, in this order: the producer must be `ACTIVE` at application submission and at issue (`ERR_PRODUCER_SUSPENDED`); the license gate requires an `ACTIVE` license covering the needed lines of authority (`ERR_LICENSE_NOT_ACTIVE`); the renewal gate requires a compliant CE determination (`ERR_CE_INCOMPLETE`); the appointment gate requires an `ACTIVE` appointment, the producer's own or the affiliated agency's (`ERR_APPOINTMENT_NOT_ACTIVE`); and the commission-hold gates reject unreleasable or still-regulated holds (`ERR_HOLD_NOT_RELEASABLE`, `ERR_REGULATORY_HOLD_ACTIVE`). Structural constraints come next: subject exclusivity (`ERR_LICENSE_SUBJECT_CONFLICT`), the one-open-license rule (`ERR_DUPLICATE_LICENSE`), the one-open-appointment rule (`ERR_APPOINTMENT_ALREADY_ACTIVE`), and CE applicability (`ERR_CE_NOT_APPLICABLE`). Temporal rules are evaluated after that: the renewal window (`ERR_RENEWAL_WINDOW_CLOSED`), appointment-interval overlap (`ERR_APPOINTMENT_INTERVAL_OVERLAP`), the for-cause termination filing deadline (`ERR_TERMINATION_FILING_OVERDUE`), and probation spacing (`ERR_PROBATION_SPACING`). Finally come the fiscal floor on submission premium (`ERR_PREMIUM_BELOW_MINIMUM`, HTTP 422) and the referential guard on producer reinstatement (`ERR_OVERDUE_INQUIRY_EXISTS`).

Independently of this ordering, any request that is malformed in itself — a missing required field, an invalid enum value, a malformed datetime, a non-positive `credit_hours`, an `expiration_date` not strictly after `issue_date`, or a uniqueness collision on a producer's `npn` or an inquiry's `reference_number` — is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Producers, Agencies, and the Licensing Record

Everything in the platform anchors on the producer and agency records. A `LicensingCoordinator` or `CarrierAdmin` creates an agency by supplying its legal `name` and its two-letter home state in `resident_state_code`. A `LicensingCoordinator` creates a producer with the producer's National Producer Number in `npn` — unique across all producers, with a collision rejected as `ERR_INVALID_REQUEST` — plus `full_name`, a two-letter `resident_state_code`, and optionally an `agency_id` affiliating the producer to an existing agency; leaving `agency_id` null registers an independent producer. A new producer starts `ACTIVE`, with both derived counters, `ytd_issued_premium_cents` and `commission_held_cents`, at zero. The producer list may be filtered by `agency_id` and `status`.

A producer's `status` moves between `ACTIVE` and `SUSPENDED`; there is no terminal state for a producer. Suspension is never requested directly — it arrives only as a cascade from an overdue regulatory inquiry (§3.8). Reinstatement is the inverse: a `ComplianceOfficer` reinstates a `SUSPENDED` producer to `ACTIVE`, but only when no regulatory inquiry naming that producer is still `OVERDUE`; attempting reinstatement while one remains overdue is rejected with `ERR_OVERDUE_INQUIRY_EXISTS` (HTTP 409).

Licenses are issued to a single subject per the exclusivity rule of §2.6. Creating a license takes, beyond its subject, the two-letter `state_code` of licensure, a `license_class` of `RESIDENT` or `NON_RESIDENT`, a non-empty `lines_of_authority` subset drawn from `LIFE`, `ACCIDENT_HEALTH`, `PROPERTY`, `CASUALTY`, and `PERSONAL_LINES`, the `issue_date`, and an `expiration_date` that must fall strictly after `issue_date` (otherwise `ERR_INVALID_REQUEST`). Two CE inputs are optional at creation: `ce_required_hours`, defaulting to 24, and `ce_ethics_required_hours`, defaulting to 3 — agency-held licenses conventionally take 0 here. A new license starts `ACTIVE`, with its current compliance period running from `ce_period_start` (initialized to the `issue_date`) to `ce_period_end` (initialized to the `expiration_date`), both CE progress counters `ce_completed_hours` and `ce_ethics_completed_hours` at zero, and `renewed_count` at zero. At most one non-terminal license may exist per subject and state — any license whose status is not `REVOKED` counts as non-terminal — and creating a second is rejected with `ERR_DUPLICATE_LICENSE` (HTTP 409). The license list may be filtered by `producer_id`, `agency_id`, `state_code`, and `status`.

### 3.2. Continuing Education and the Compliance Determination

Producers maintain their licenses by completing continuing-education courses and reporting the credits. A `Producer` reports credits against their own licenses, and a `LicensingCoordinator` may report on a producer's behalf. Each credit record carries the target `license_id`, the `provider_name`, the `course_title`, a `category` of `GENERAL` or `ETHICS`, the `credit_hours` earned — which must be greater than zero and carry at most one decimal place, else `ERR_INVALID_REQUEST` — and the `completed_on` instant. Credits may only be reported against producer-held licenses; attempting to report one against an agency-held license is rejected with `ERR_CE_NOT_APPLICABLE`. A newly reported credit starts in `REPORTED` status, and the credit list may be filtered by `license_id` and `status`.

A `LicensingCoordinator` reviews each `REPORTED` credit by submitting a `decision` of `ACCEPT` or `REJECT`, moving it to `ACCEPTED` or `REJECTED` — both terminal. The review records the coordinator's identity in `reviewed_by_user_id`. On either outcome the license's CE counters are recomputed; an acceptance can change them (and therefore increments the license's `version`), while rejected credits never count. Reviewing a credit that is already terminal is rejected with `ERR_INVALID_STATE`.

The compliance determination behind every renewal works as follows. The input set is the license's `ACCEPTED` credits whose `completed_on` falls within the current compliance period — from `ce_period_start` through `ce_period_end`, both ends inclusive; `REPORTED` and `REJECTED` credits are excluded. Within that set, the ethics total is the sum of `credit_hours` over `ETHICS`-category credits, and the general total is the sum over `GENERAL`-category credits. What the totals must satisfy depends on `license_class`, and the two variants differ in how ethics hours count toward the total requirement.

For a `RESIDENT` license, the spillover variant applies: all accepted hours count toward the total. The license's `ce_ethics_completed_hours` displays the ethics total capped at `ce_ethics_required_hours`, and its `ce_completed_hours` displays the combined ethics-plus-general total capped at `ce_required_hours`. The license is `COMPLIANT` exactly when the combined ethics-plus-general total is at least `ce_required_hours` and the ethics total is at least `ce_ethics_required_hours`.

For a `NON_RESIDENT` license, the strict variant applies: ethics hours count only toward the ethics sub-requirement. The `ce_ethics_completed_hours` display is the same capped value, but `ce_completed_hours` is the smaller of the ethics total and `ce_ethics_required_hours`, plus the general total. The license is `COMPLIANT` exactly when the general total alone is at least the total requirement minus the ethics requirement, and the ethics total is at least `ce_ethics_required_hours`.

### 3.3. License Renewal, Expiration, and Reinstatement

Licenses age out in two ways. The clock sweep moves an `ACTIVE` license to `EXPIRED` once the clock passes its `expiration_date`; and confirmed regulatory actions can drive a license to `SUSPENDED` or `REVOKED`, with the cascades described in §3.7. `REVOKED` is terminal.

Renewal is a `LicensingCoordinator` operation guarded by three preconditions, checked in this order. First, optimistic concurrency: the request must carry `expected_license_version` equal to the license's current `version`, else `ERR_STALE_VERSION`. Second, the renewal window must be open: from `ACTIVE`, the window runs from ninety days before the `expiration_date` through the `expiration_date` itself, both ends inclusive; from `EXPIRED`, a grace leg runs from strictly after the `expiration_date` through thirty days past it, the far end inclusive. Outside both legs the renewal is rejected with `ERR_RENEWAL_WINDOW_CLOSED`. Third, the CE determination of §3.2 must come out `COMPLIANT`, else `ERR_CE_INCOMPLETE`. Attempting to renew a license in any other status — `SUSPENDED` or `REVOKED` — is a plain state error, `ERR_INVALID_STATE`.

A successful renewal extends the `expiration_date` by 24 months, measured from the prior expiration. The compliance period rolls forward with it: `ce_period_start` becomes the prior `ce_period_end`, and `ce_period_end` becomes the new `expiration_date`. Both progress counters, `ce_completed_hours` and `ce_ethics_completed_hours`, reset to zero, and `renewed_count` increases by one; the license's `version` increments as with any mutation. A renewal from `EXPIRED` additionally restores the status to `ACTIVE`; its period and counter resets are identical to an in-window renewal.

Reinstatement is the regulatory cure, reserved for a `ComplianceOfficer`: a `SUSPENDED` license returns to `ACTIVE` with a version increment. Reinstatement deliberately does not restore the appointments that were cascaded into termination when the suspension landed; a coordinator may rescue those individually through rescission (§3.4).

### 3.4. Appointments: Standard Filings, Just-in-Time Triggers, and Terminations

An appointment authorizes a subject to write the carrier's business in one state. A `LicensingCoordinator` requests a standard appointment by naming its subject (per §2.6), the `state_code`, the requested `lines_of_authority`, and an `effective_date`; back-dating the effective instant is permitted so an appointment can cover prior sales. A standard appointment is created with `origin` set to `STANDARD` and status `REQUESTED`, awaiting filing.

Two uniqueness rules guard appointment creation. At most one non-terminal appointment — one in `REQUESTED`, `JIT_PENDING`, `ACTIVE`, or `TERMINATION_PENDING` — may exist per subject and `state_code`; creating a second is rejected with `ERR_APPOINTMENT_ALREADY_ACTIVE`. And the requested `effective_date` must not fall inside any other of the same subject's appointment intervals in that state, where each interval runs from its `effective_date` up to but not including its `termination_date`; because the interval is half-open, an effective date that exactly equals a prior appointment's termination date does not overlap. A violation is rejected with `ERR_APPOINTMENT_INTERVAL_OVERLAP`. Both rules bind system-created just-in-time appointments as well, whose effective instant is the triggering application's submission time.

Filing is the act that turns a request into authority, performed by a `LicensingCoordinator`. Filing a `REQUESTED` appointment requires the subject to hold an `ACTIVE` license in the appointment's `state_code` whose `lines_of_authority` cover every requested line, else `ERR_LICENSE_NOT_ACTIVE`; on success the appointment becomes `ACTIVE` with its `effective_date` unchanged from creation. Filing a `JIT_PENDING` appointment carries the same license-coverage precondition plus a timeliness one: the clock must not have passed the appointment's `jit_filing_deadline`, and filing exactly at the deadline instant is timely. Once the sweep has moved a just-in-time appointment to `LAPSED`, filing it is rejected with `ERR_JIT_FILING_WINDOW_CLOSED`. `LAPSED` and `TERMINATED` are the terminal states of an appointment.

Termination begins when a `LicensingCoordinator` terminates an `ACTIVE` appointment, supplying a `termination_reason` of `VOLUNTARY` or `FOR_CAUSE` — omitting the reason is rejected with `ERR_INVALID_REQUEST`. The appointment moves to `TERMINATION_PENDING`, with `termination_initiated_at` stamped to the clock. From there, two outcomes exist. The coordinator may rescind the termination, returning the appointment to `ACTIVE` and clearing `termination_reason` and `termination_initiated_at` while leaving `effective_date` untouched; rescission requires the subject's license in that state to be `ACTIVE`, else `ERR_LICENSE_NOT_ACTIVE`. Or the coordinator may file the termination with the state, moving the appointment to `TERMINATED` and stamping `termination_date` to the clock; a `FOR_CAUSE` termination must be filed no later than thirty days after `termination_initiated_at`, and filing later is rejected with `ERR_TERMINATION_FILING_OVERDUE`.

A third termination reason exists that no coordinator may supply directly: `LICENSE_INACTIVE` is written by the disciplinary cascade of §3.7 when a confirmed regulatory action suspends or revokes the subject's license, driving each `ACTIVE` appointment in that state to `TERMINATION_PENDING`. The appointment list may be filtered by `producer_id`, `agency_id`, `state_code`, and `status`.

### 3.5. Policy Applications from Submission to Issue

A policy application is the revenue event every other control exists to police. A `Producer` submits applications for their own book — the payload `producer_id` must equal their `X-User-ID` — while a `LicensingCoordinator` may submit on any producer's behalf. Submission names the `state_code` where the risk is written, a single `line_of_authority` from the five-line catalog, the insured's `applicant_name`, and the written `premium_cents`, which must be at least 500 cents (five dollars); anything less is rejected with `ERR_PREMIUM_BELOW_MINIMUM` (HTTP 422). The producer must be `ACTIVE` at submission, else `ERR_PRODUCER_SUSPENDED`.

At submission the platform stamps `submitted_at` from the logical clock, sets the status to `SUBMITTED`, and evaluates the producer's eligibility posture for the submitted state and line. The posture derivation has a fixed precedence: if the producer is not `ACTIVE` the posture is `PRODUCER_SUSPENDED`; otherwise, if the producer holds no `ACTIVE` license in the state covering the line, the posture is `LICENSE_GAP`; otherwise, if no `ACTIVE` appointment covering the line is held in the state by the producer or by the producer's affiliated agency, the posture is `APPOINTMENT_GAP`; otherwise the posture is `ELIGIBLE`. The outcome is persisted on the application as `eligibility_snapshot`, and it is re-evaluated at issue time. Because both submission and issue require an `ACTIVE` producer, `PRODUCER_SUSPENDED` never persists in the snapshot — it exists only as the live answer of the eligibility query in §3.9.

A snapshot of `APPOINTMENT_GAP` triggers the platform's just-in-time machinery: submission automatically creates an appointment with `origin` set to `JIT` and status `JIT_PENDING`, whose `lines_of_authority` contains exactly the application's `line_of_authority`, whose `effective_date` is the application's `submitted_at`, and whose `jit_filing_deadline` is fifteen days after `submitted_at`. The application records the link in `jit_appointment_id`, and the coordinator has that fifteen-day window to file the appointment before the sweep lapses it (§3.4). A snapshot of `LICENSE_GAP` creates no appointment — there is nothing to appoint against until the producer is licensed.

Submission also creates the application's commission entry, with `application_id` and `producer_id` copied from the application itself. The entry's initial posture mirrors the snapshot: `ELIGIBLE` business starts `PAYABLE`; an `APPOINTMENT_GAP` starts `HELD` with `hold_reason` `APPOINTMENT_PENDING`; a `LICENSE_GAP` starts `HELD` with `hold_reason` `UNLICENSED_AT_SALE`. The amount is the provisional figure of §3.6. The application list may be filtered by `producer_id`, `status`, and `jit_appointment_id`.

Decision is a `LicensingCoordinator` action carrying a `decision` of `APPROVE` or `DECLINE`. Approving requires the producer to hold an `ACTIVE` license in the application's state covering its line, else `ERR_LICENSE_NOT_ACTIVE`; an approved application moves from `SUBMITTED` to `APPROVED` with `decided_at` stamped. Declining moves it to `DECLINED` — terminal — and forfeits its commission entry regardless of the entry's then-current non-terminal status, after which the producer's held-commission total is recomputed. The same decline-and-forfeit cascade fires automatically if the producer is suspended while an application still sits `SUBMITTED`: the application is `DECLINED` with `decided_at` stamped, and its commission entry is forfeited.

Issuing an `APPROVED` application is again a `LicensingCoordinator` action, gated twice: the producer must still be `ACTIVE` (`ERR_PRODUCER_SUSPENDED`), and an `ACTIVE` appointment covering the application's line in its state must exist — either the producer's own or one held by the producer's affiliated agency — else `ERR_APPOINTMENT_NOT_ACTIVE`. On issue the application becomes `ISSUED` with `issued_at` stamped, the `eligibility_snapshot` is re-evaluated, the producer's year-to-date issued premium is recomputed with this application now in the input set, and the commission entry is repriced to its final figure per §3.6.

Rescission unwinds an issued policy: a `LicensingCoordinator` rescinds an `ISSUED` application to `RESCINDED`, terminal. The application leaves the year-to-date input set (the producer's total is recomputed), and its commission entry — whatever its status — is forfeited, with the held total recomputed.

### 3.6. Commissions: Tiered Amounts, Holds, and Settlement

Every commission amount derives from three inputs: the application's `premium_cents`, the base commission rate fixed for the application's `line_of_authority`, and two multipliers. The volume multiplier steps with the producer's year-to-date issued premium at the evaluation instant: 1.00 while that total is below 100,000,000 cents (one million dollars), 1.10 once it reaches one million dollars but remains below 500,000,000 cents (five million dollars), and 1.25 once it reaches five million dollars. The agency uplift is 1.05 when the producer is affiliated with an agency and that agency holds an `ACTIVE` appointment in the application's state covering the application's line, and 1.00 otherwise. The amount in `amount_cents` is the premium multiplied by the base rate, then by the volume multiplier, then by the uplift, with the product rounded down to a whole cent — that rounding applied exactly once, at the very end.

The year-to-date figure behind the volume multiplier, exposed on the producer as `ytd_issued_premium_cents`, is the sum of `premium_cents` over the producer's applications in `ISSUED` status whose `issued_at` falls within the logical clock's current calendar year — from January 1 at 00:00:00 UTC inclusive up to the following January 1 exclusive. It is recomputed on every issue and every rescind. Discrete issue calls are processed in request order, each observing the total accumulated from previously processed issues; any system batch over same-instant issues orders them by `issued_at` ascending, then by application `created_at` ascending.

Timing splits the calculation into two variants, recorded on the entry as `amount_variant`. The `PROVISIONAL` figure is computed at submission, using the year-to-date total as it stood at that moment. At issue the entry is repriced to the `FINAL` figure, with the volume multiplier read from the year-to-date total at issue time computed before the issuing application's own premium enters the input set — so a single application can never tier itself up, though it raises the tier of everything issued after it.

The entry's `status` walks `HELD`, `PAYABLE`, `PAID`, and `FORFEITED`, with `PAID` and `FORFEITED` terminal; `hold_reason` is null unless the entry is `HELD`, when it is one of `APPOINTMENT_PENDING`, `UNLICENSED_AT_SALE`, or `REGULATORY_HOLD`. The producer's `commission_held_cents` is the sum of `amount_cents` across their `HELD` entries, recomputed on every commission status change.

Release is a `ComplianceOfficer` decision, and the gate depends on why the money was held. A hold whose `hold_reason` is `UNLICENSED_AT_SALE` is never releasable — release is always rejected with `ERR_HOLD_NOT_RELEASABLE`. For `APPOINTMENT_PENDING`, release requires an `ACTIVE` appointment covering the application's line in the application's state, held by the producer or the affiliated agency, else `ERR_APPOINTMENT_NOT_ACTIVE`. For `REGULATORY_HOLD`, release requires the producer's license in the application's state to be `ACTIVE` again, else `ERR_REGULATORY_HOLD_ACTIVE`. A successful release moves the entry to `PAYABLE`, clears `hold_reason`, and recomputes the producer's held total. Releasing an entry that is not `HELD` at all is a plain `ERR_INVALID_STATE`.

Payment belongs to `FinanceOps`: paying moves a `PAYABLE` entry to `PAID`, and paying anything not `PAYABLE` is rejected with `ERR_COMMISSION_NOT_PAYABLE`. Two system-driven transitions complete the picture. When a confirmed regulatory action suspends or revokes the producer's license in the entry's application state, each of that producer's `PAYABLE` entries falls back to `HELD` with `hold_reason` `REGULATORY_HOLD` (§3.7). And forfeiture — from a decline, a rescind, or a revocation landing on `UNLICENSED_AT_SALE` holds — moves entries to `FORFEITED`, recomputing the held total each time. The commission list may be filtered by `application_id`, `producer_id`, and `status`.

### 3.7. Regulatory Actions, Maker-Checker Review, and Disciplinary Cascades

When a state regulator moves against a producer or agency, a `ComplianceOfficer` reports the action, naming the subject (per §2.6), the `state_code` bringing the action, an `action_type` of `FINE`, `SUSPENSION`, `REVOCATION`, or `PROBATION`, and the action's `effective_date`. A `FINE` additionally requires `fine_amount_cents`, which must be greater than zero; for any other action type it stays null, and a missing or non-positive fine amount is `ERR_INVALID_REQUEST`. The report records the reporter in `created_by_user_id` and starts in `REPORTED` status. The action list may be filtered by `producer_id`, `agency_id`, and `status`.

A different `ComplianceOfficer` must then adjudicate the report — the maker-checker rule of §2.1 rejects confirmation or dismissal by the original reporter with `ERR_SOD_VIOLATION`, and whichever officer acts is recorded in `decided_by_user_id`. Dismissal simply moves the action to `DISMISSED`, terminal. Confirmation moves it to `CONFIRMED`, also terminal, and fires the consequences below.

Confirming a `PROBATION` carries a spacing rule: the action's `effective_date` must be at least 365 days after the effective date of any other already-`CONFIRMED` probation against the same subject in the same state; a probation that lands inside that 365-day gap is rejected with `ERR_PROBATION_SPACING`.

Confirming a `SUSPENSION` or `REVOCATION` cascades through the book. The matching license — same subject, same `state_code` — moves from `ACTIVE` to `SUSPENDED`, or from `ACTIVE` (or already `SUSPENDED`) to `REVOKED`. Every one of the subject's `ACTIVE` appointments in that state follows to `TERMINATION_PENDING` with `termination_reason` `LICENSE_INACTIVE` and `termination_initiated_at` stamped, each such appointment mutation incrementing its `version`. The cascade then reaches commissions: every one of the producer's entries with status `PAYABLE` is re-held as `HELD` with `hold_reason` `REGULATORY_HOLD`, and the producer's `commission_held_cents` is recomputed. A revocation goes one step further: every entry already `HELD` with `hold_reason` `UNLICENSED_AT_SALE` is forfeited outright, again recomputing the held total. `REVOKED` being terminal, only the reinstatement of a suspension (§3.3) offers a way back, and even that leaves the cascaded appointments in `TERMINATION_PENDING` for individual rescue.

Confirming a `FINE` allocates the fine across the producer's issued business in the action's state, storing the result in `fine_allocations`. The input set is the subject producer's applications with status `ISSUED` in the action's `state_code`, ordered by `premium_cents` descending with `created_at` ascending as the tie-break; if that set is empty — or the action is not a fine — `fine_allocations` is an empty list. Otherwise, each application's raw share is the fine amount multiplied by the application's `premium_cents` and divided by the total premium of the set; each raw share is rounded down to a whole cent; and the difference between the fine amount and the sum of the rounded shares is then distributed one cent at a time to applications in that same order until the fine is fully allocated. The result is a list of allocation objects in input-set order, each pairing the source `application_id` with its final `allocated_cents` share.

### 3.8. Regulatory Inquiries and the Response Clock

A department-of-insurance inquiry starts when a `ComplianceOfficer` opens one against a subject (per §2.6), naming the inquiring `state_code` and the external `reference_number`, which must be unique across all inquiries — a duplicate is `ERR_INVALID_REQUEST`. The inquiry stamps `received_at` from the logical clock, computes its `response_due_at` as thirty days after receipt, and opens in `OPEN` status. The inquiry list may be filtered by `producer_id`, `agency_id`, and `status`.

The response clock is enforced by the sweep. Once the clock passes `response_due_at`, an `OPEN` inquiry turns `OVERDUE`, and the consequences are severe: when the inquiry names a producer who is currently `ACTIVE`, that producer is suspended, and the producer-suspension cascade of §3.5 fires — every one of that producer's still-`SUBMITTED` applications is declined with `decided_at` stamped, each such application's commission entry is forfeited from any non-terminal status, and the producer's held-commission total is recomputed.

Answering the inquiry is shared between `LicensingCoordinator` and `ComplianceOfficer`, and is allowed from both `OPEN` and `OVERDUE`. The response carries the narrative `response_text` and the OCC guard `expected_inquiry_version`; a version that has since advanced — most commonly because the sweep moved the inquiry to `OVERDUE` — is rejected with `ERR_STALE_VERSION`. A successful response moves the inquiry to `RESPONSE_SUBMITTED` and stamps `responded_at`. Notably, a late response does not reinstate the suspended producer; that takes the explicit reinstatement of §3.1, which remains blocked with `ERR_OVERDUE_INQUIRY_EXISTS` while any inquiry naming the producer is still `OVERDUE`. Closing the file is a `ComplianceOfficer` action that moves a `RESPONSE_SUBMITTED` inquiry to `CLOSED`, terminal; attempting to close an inquiry still `OPEN` or `OVERDUE` is `ERR_INVALID_STATE`.

### 3.9. Eligibility Posture as a Computed Read

The same posture derivation used at submission and issue is also available as a live query, answering whether a given producer could write a given line in a given state right now. Given `state_code` and `line_of_authority`, the read returns `eligibility_status` — one of `ELIGIBLE`, `LICENSE_GAP`, `APPOINTMENT_GAP`, or `PRODUCER_SUSPENDED`, derived with the fixed precedence of §3.5 — together with the `license_id` and `appointment_id` of the covering records, each null when no such covering record exists, and `via_agency`, true exactly when only the affiliated agency's appointment provides the coverage. All five roles may issue the query, subject to the `Producer` role's ownership scoping. The query has no side effects; it exists so coordinators can check posture before writing business, and so producers can see why a commission is held.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. All other successful operations — reads, state transitions, decisions, payments, and the computed eligibility query — return `200 OK`. Request and response payloads for each operation are governed by the narratives of §2 and §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/agencies` | Create an agency | LicensingCoordinator, CarrierAdmin |
| POST | `/api/producers` | Create a producer (optionally affiliated to an agency) | LicensingCoordinator |
| GET | `/api/producers/{producerId}` | Get a producer (Producer role: self only) | LicensingCoordinator, ComplianceOfficer, FinanceOps, CarrierAdmin, Producer |
| GET | `/api/producers` | List producers with filters | LicensingCoordinator, ComplianceOfficer, FinanceOps, CarrierAdmin |
| POST | `/api/producers/{producerId}/reinstate` | Reinstate a SUSPENDED producer | ComplianceOfficer |
| POST | `/api/licenses` | Create a producer- or agency-held license | LicensingCoordinator |
| GET | `/api/licenses/{licenseId}` | Get a license | LicensingCoordinator, ComplianceOfficer, FinanceOps, CarrierAdmin, Producer |
| GET | `/api/licenses` | List licenses with filters | LicensingCoordinator, ComplianceOfficer, CarrierAdmin |
| POST | `/api/licenses/{licenseId}/renew` | Renew a license (OCC-guarded; windowed; requires CE compliance) | LicensingCoordinator |
| POST | `/api/licenses/{licenseId}/reinstate` | Reinstate a SUSPENDED license to ACTIVE | ComplianceOfficer |
| POST | `/api/ce-credits` | Report a CE credit against a producer-held license | Producer, LicensingCoordinator |
| GET | `/api/ce-credits/{ceCreditId}` | Get a CE credit | LicensingCoordinator, ComplianceOfficer, CarrierAdmin, Producer |
| GET | `/api/ce-credits` | List CE credits with filters | LicensingCoordinator, ComplianceOfficer, CarrierAdmin |
| POST | `/api/ce-credits/{ceCreditId}/review` | Accept or reject a REPORTED CE credit | LicensingCoordinator |
| POST | `/api/appointments` | Request a STANDARD appointment for a producer or agency | LicensingCoordinator |
| GET | `/api/appointments/{appointmentId}` | Get an appointment | LicensingCoordinator, ComplianceOfficer, CarrierAdmin, Producer |
| GET | `/api/appointments` | List appointments with filters | LicensingCoordinator, ComplianceOfficer, CarrierAdmin |
| POST | `/api/appointments/{appointmentId}/file` | File a REQUESTED or JIT_PENDING appointment with the state | LicensingCoordinator |
| POST | `/api/appointments/{appointmentId}/terminate` | Initiate termination of an ACTIVE appointment | LicensingCoordinator |
| POST | `/api/appointments/{appointmentId}/file-termination` | File a pending termination with the state | LicensingCoordinator |
| POST | `/api/appointments/{appointmentId}/rescind-termination` | Rescind a pending termination | LicensingCoordinator |
| POST | `/api/applications` | Submit a policy application | Producer, LicensingCoordinator |
| GET | `/api/applications/{applicationId}` | Get an application | LicensingCoordinator, ComplianceOfficer, CarrierAdmin, Producer |
| GET | `/api/applications` | List applications with filters | LicensingCoordinator, ComplianceOfficer, CarrierAdmin |
| POST | `/api/applications/{applicationId}/decide` | Approve or decline a SUBMITTED application | LicensingCoordinator |
| POST | `/api/applications/{applicationId}/issue` | Issue an APPROVED application | LicensingCoordinator |
| POST | `/api/applications/{applicationId}/rescind` | Rescind an ISSUED application | LicensingCoordinator |
| GET | `/api/commission-entries/{commissionEntryId}` | Get a commission entry | LicensingCoordinator, ComplianceOfficer, FinanceOps, CarrierAdmin, Producer |
| GET | `/api/commission-entries` | List commission entries with filters | LicensingCoordinator, ComplianceOfficer, FinanceOps, CarrierAdmin |
| POST | `/api/commission-entries/{commissionEntryId}/release` | Release a HELD commission to PAYABLE per hold-reason gates | ComplianceOfficer |
| POST | `/api/commission-entries/{commissionEntryId}/pay` | Pay a PAYABLE commission | FinanceOps |
| POST | `/api/regulatory-actions` | Report a regulatory action against a producer or agency | ComplianceOfficer |
| GET | `/api/regulatory-actions/{regulatoryActionId}` | Get a regulatory action | LicensingCoordinator, ComplianceOfficer, CarrierAdmin, Producer |
| GET | `/api/regulatory-actions` | List regulatory actions with filters | LicensingCoordinator, ComplianceOfficer, CarrierAdmin |
| POST | `/api/regulatory-actions/{regulatoryActionId}/confirm` | Confirm a REPORTED action (maker-checker; fires cascades and fine allocation) | ComplianceOfficer |
| POST | `/api/regulatory-actions/{regulatoryActionId}/dismiss` | Dismiss a REPORTED action (maker-checker) | ComplianceOfficer |
| POST | `/api/inquiries` | Open a regulatory inquiry against a producer or agency | ComplianceOfficer |
| GET | `/api/inquiries/{inquiryId}` | Get an inquiry | LicensingCoordinator, ComplianceOfficer, CarrierAdmin, Producer |
| GET | `/api/inquiries` | List inquiries with filters | LicensingCoordinator, ComplianceOfficer, CarrierAdmin |
| POST | `/api/inquiries/{inquiryId}/response` | Submit an inquiry response (OCC-guarded; allowed from OPEN and OVERDUE) | LicensingCoordinator, ComplianceOfficer |
| POST | `/api/inquiries/{inquiryId}/close` | Close a RESPONSE_SUBMITTED inquiry | ComplianceOfficer |
| GET | `/api/producers/{producerId}/eligibility` | Computed eligibility posture of a producer for a state and line of authority | LicensingCoordinator, ComplianceOfficer, FinanceOps, CarrierAdmin, Producer |
| POST | `/_clock/set_current_utc` | Set the logical clock and run the compliance sweep | CarrierAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is an identifier summary only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PRODUCER_SUSPENDED` | 409 Conflict |
| `ERR_LICENSE_NOT_ACTIVE` | 409 Conflict |
| `ERR_CE_INCOMPLETE` | 409 Conflict |
| `ERR_CE_NOT_APPLICABLE` | 409 Conflict |
| `ERR_DUPLICATE_LICENSE` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_APPOINTMENT_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_APPOINTMENT_INTERVAL_OVERLAP` | 409 Conflict |
| `ERR_JIT_FILING_WINDOW_CLOSED` | 409 Conflict |
| `ERR_RENEWAL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_TERMINATION_FILING_OVERDUE` | 409 Conflict |
| `ERR_HOLD_NOT_RELEASABLE` | 409 Conflict |
| `ERR_REGULATORY_HOLD_ACTIVE` | 409 Conflict |
| `ERR_COMMISSION_NOT_PAYABLE` | 409 Conflict |
| `ERR_PREMIUM_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_PROBATION_SPACING` | 409 Conflict |
| `ERR_OVERDUE_INQUIRY_EXISTS` | 409 Conflict |

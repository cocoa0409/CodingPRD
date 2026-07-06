# Traffic Enforcement API — Product Requirements Document

## 1. Introduction

Automated traffic enforcement programs sit at an uncomfortable intersection of public safety, due process, and municipal revenue, and the software that runs them has to satisfy all three at once. This document specifies the API for an automated red-light and speed-camera enforcement platform. It governs the full arc of an enforcement event: a camera captures a suspected violation, a human review officer examines the evidence, the registered owner of the plate is looked up and mailed a notice, a statutory fine plus administrative fee is assessed, and the owner is then given a fair chance to pay, or to contest the citation and be heard by an independent adjudicator.

The design is built around a strict separation of duties: the officer who reviews captured evidence may never be the adjudicator who later rules on a contest of that same citation, and the camera vendor whose hardware generated the revenue has no ability to touch the review or adjudication pipeline at all. Every money-moving event — the assessment of a fine, the accrual of a vendor's revenue share, the escalation of an unpaid citation into delinquency, the reversal of a cleared payment — must be reproducible, auditable, and reversible where the law requires compensation. Because deadlines, hearing dates, and escalation windows are central to the domain, the system runs on a controllable logical clock rather than wall-clock time, so that the passage of a response window or the arrival of a hearing date can be driven deterministically.

The reader should treat this document as the single authoritative contract. Fine schedules, escalation triggers, calibration requirements, and the cascading effects of voiding or reversing are all described in the business-logic narrative of Section 3; the global rules that cut across every entity live in Section 2; and the endpoint and error catalogues in Sections 4 and 5 are deliberately terse indexes back into that narrative.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to a staff-facing endpoint must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This is the first check applied to any staff endpoint, evaluated before role authorization, existence, or any business rule.

The system recognizes six roles, spelled exactly as follows: `SystemAdmin`, `ProgramAdmin`, `ReviewOfficer`, `Adjudicator`, `RegisteredOwner`, and `Auditor`. When a request presents valid headers but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403). The authoritative role-to-operation mapping is the "Authorized Role(s)" column of the endpoint table in Section 4.

Five of the six roles carry an **opaque identity**: for `SystemAdmin`, `ProgramAdmin`, `ReviewOfficer`, `Adjudicator`, and `Auditor`, the value of `X-User-ID` is an operator identifier that is not tied to any persisted entity. The server may record such an identifier where a workflow calls for it — for example, it stores the reviewing officer's `X-User-ID` on the citation as `review_officer_ref`, and it stores the ruling adjudicator's `X-User-ID` as `adjudicator_ref` on the hearing — but it never compares that value to any entity's `id`.

The `RegisteredOwner` role is different: it is **entity-backed**. A `RegisteredOwner` does not authenticate with the staff headers at all. Instead, owner-portal operations authenticate by presenting a `registered_owner_id` together with the `portal_access_pin` that the server minted for that owner at registration time. When the pair does not match a registered owner, the request is rejected with `ERR_PORTAL_AUTH_FAILED` (HTTP 401). This portal-PIN check is the authentication mechanism for the owner-facing operations — filing a contest, listing one's own citations through the portal, and reading one's own evidence — and it stands in place of the `X-User-Role`/`X-User-ID` header check for those endpoints. When an owner acts, the acting owner is the `RegisteredOwner` whose `registered_owner_id` and `portal_access_pin` were presented; ownership of any citation, contest, or payment the owner touches is established through that owner identity rather than through a header.

A note on the segregation of duties that runs through the whole system: an `Adjudicator` may never rule on, or be assigned to, a hearing for a citation they themselves reviewed. Concretely, the adjudicator's `X-User-ID` must differ from the citation's stored `review_officer_ref`; a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, list results are ordered by their creation timestamp (`created_at`) in ascending order.

Every list response reports pagination state inside the envelope's `meta` object using the fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Audit-Log Records

Most resources in this system carry a common set of server-managed fields. Every `Program`, `Camera`, `RegisteredOwner`, `Citation`, `Contest`, `Hearing`, `Payment`, and `VendorContract` includes:

- `id` — a unique, server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that starts at its initial value on creation and increments by one on every mutation. It is the basis for the optimistic concurrency control described in Section 2.6.

Two resource types are deliberately leaner because they are append-only audit artifacts and are never mutated after creation. A `CalibrationRecord` and a `NoticeRecord` carry only an `id` and a `created_at`; they have neither an `updated_at` nor a `version` field. A `NoticeRecord` is an immutable log entry emitted once per notice-generating event on a citation — one at initial issuance and one at each delinquency escalation — and is described further in Section 3.

Whenever an operation mutates a resource, that resource's `updated_at` is refreshed and its `version` is incremented. This holds equally for derived-field updates: when a payment clearing recomputes a citation's `amount_paid_cents`, or when a vendor's `accrued_vendor_share_cents` changes, those are mutations that bump the affected resource's `updated_at` and `version`.

### 2.5. Monetary Values, Precision, and Rounding

All monetary amounts in this system are integer counts of cents; there are no fractional-cent values in stored fields or in API responses. Two computations nonetheless involve multiplication and therefore require an explicit rounding rule, and both use **round half up** to the nearest whole cent: the application of a speed-band multiplier and repeat-offender surcharge when a fine is assessed (Section 3.4), and the application of a vendor's revenue-share percentage (Section 3.7). Where a calculation is pure integer addition — such as re-adding the administrative fee to a reduced fine, or adding a flat late fee — no rounding is involved.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control (OCC), each keyed to the current `version` of a specific parent resource. In each case the request must carry an expected-version field, and that field is **not optional** on the guarded operation.

Filing a contest against a citation is guarded on the parent `Citation`. The request must include `expected_citation_version` carrying the client's last observed `version` of the target citation. If that value does not match the citation's current `version` — because another writer has advanced the citation since the owner last read it, for example a review re-decision or an escalation sweep that changed the citation's state and bumped its version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), so that the owner cannot file against a citation whose current state they have not observed.

Ruling on a hearing is guarded on the parent `Hearing`. The request must include `expected_hearing_version` carrying the adjudicator's last observed `version` of the target hearing. If that value does not match the hearing's current `version` — because, for instance, a citation-void cascade adjourned the hearing and bumped its version after the adjudicator loaded it — the ruling is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field, and no other endpoint performs an OCC check.

### 2.7. Resource Existence and Left-to-Right Path Validation

When an endpoint path names one or more resources, the system validates them in left-to-right order and rejects the request at the first identifier that does not resolve to an existing resource, with `ERR_NOT_FOUND` (HTTP 404). For a nested path such as the hearings of a contest, the contest is checked before any hearing is sought. The same existence discipline applies to body-referenced foreign keys on citation capture: the referenced `program_id` and `camera_id` must exist and belong to the same program, and a mismatch or missing target yields `ERR_NOT_FOUND` as well.

### 2.8. Separation of Duties Across the Enforcement Pipeline

The enforcement pipeline is intentionally partitioned so that no single actor can both accuse and judge. A `ReviewOfficer` decides whether captured evidence becomes a citation, but has no power over hearings. An `Adjudicator` rules on hearings, but only for citations reviewed by a *different* officer. A `ProgramAdmin` runs the operational machinery of a jurisdiction — cameras, calibrations, owners, hearing scheduling, voids, payment reversals, and vendor contracts — but never reviews evidence or rules on hearings. A camera vendor has no login here at all; vendors participate only as the revenue-share counterparties recorded on a `VendorContract`, and only an `Auditor` or `ProgramAdmin` can read those accrual figures. The concrete segregation-of-duties check — adjudicator identity must differ from the citation's `review_officer_ref`, on both hearing scheduling and hearing ruling, rejected with `ERR_SEGREGATION_OF_DUTIES` — is described where those operations appear in Section 3.

### 2.9. The Logical Clock

Every time-sensitive decision in this system — whether a response window has elapsed, whether a contest is still timely, whether a scheduled hearing has arrived, whether a citation has crossed its delinquency deadline — is measured against a single server-held logical clock, never against wall-clock time. On startup the logical clock reads exactly `2026-05-01T00:00:00Z`, and until it is explicitly set it stays at that default and never falls back to wall-clock. A `SystemAdmin` may advance or set the clock by supplying a target instant in the `to_iso8601` field. All computed timestamps that record "now" — a citation's `notice_issued_at_utc`, a notice record's `issued_at_clock` — are read from this clock at the moment of the triggering transition.

### 2.10. Validation Ordering

When several checks could apply to a single request, they are evaluated in a fixed priority so that the returned error is deterministic. Authentication comes first: the presence and validity of `X-User-Role`/`X-User-ID` (`ERR_UNAUTHENTICATED`), and for portal endpoints the `registered_owner_id`/`portal_access_pin` match (`ERR_PORTAL_AUTH_FAILED`). Authorization is next — the role permission check (`ERR_FORBIDDEN`), and then the segregation-of-duties check (`ERR_SEGREGATION_OF_DUTIES`) where it applies. Existence follows: path-referenced resources left-to-right (`ERR_NOT_FOUND`), then body-referenced foreign-key targets within the same program (`ERR_NOT_FOUND`). State legality is checked next — whether the requested transition is defined from the resource's current state (`ERR_INVALID_STATE`, HTTP 409) — followed by the OCC stale-version check (`ERR_STALE_VERSION`). Only then are the domain-specific business rules applied: the calibration-coverage, no-violation, owner-lookup, contest-window, hearing-time, reduction-range, camera-shape, duplicate, nothing-owed, payment-exists, and required-field checks described throughout Section 3. Finally, a body that is missing a required field or carries a value of the wrong type or an unknown enum member is rejected with `ERR_INVALID_REQUEST` (HTTP 422); this required-field/type check is the lowest-priority business validation and applies to all create and action endpoints.

## 3. Business Logic & Workflows

### 3.1. Programs, Cameras, and the Certification Regime

An enforcement **Program** is the top-level container a `SystemAdmin` creates, and it holds the jurisdiction's fiscal parameters. A program is created with a `jurisdiction_name` and the money knobs that drive every downstream calculation: `base_red_light_fine_cents` (the statutory base fine for a red-light violation), `base_speed_fine_cents` (the statutory base for a speed violation in the lowest band), `admin_fee_cents` (a flat administrative fee added to every issued citation), and `late_fee_cents` (a flat penalty that attaches when a citation escalates past its deadline). Three further parameters have defaults if omitted: `response_window_days` defaults to 30 and is the number of days from notice issuance until a citation is due; `repeat_offender_window_days` defaults to 365 and is the lookback that defines a repeat offense for the same owner; and `repeat_offender_surcharge_pct` defaults to 0.5, expressing the fractional surcharge on the base fine for a repeat offense — a value of 0.5 meaning a fifty-percent add-on.

Under a program, a `ProgramAdmin` registers **Cameras**. Each camera belongs to its program through `program_id`, carries a human-readable `intersection_code`, and has a `camera_type` that is exactly one of `RED_LIGHT` or `SPEED`. A speed camera must be created with a `speed_limit_mph` that is present and greater than zero, while a red-light camera must be created with `speed_limit_mph` absent or null; either shape violation is rejected with `ERR_INVALID_REQUEST`. The `intersection_code` must be unique within its program among all cameras whose `status` is not `DECOMMISSIONED`; a collision is rejected with `ERR_DUPLICATE` (HTTP 409). A camera also exposes a computed `certified_until_clock`, which reflects the latest `valid_until_utc` among passing calibration records for that camera, and is null if the camera has never had a passing certification.

A camera's `status` begins at `ACTIVE` and moves through a small lifecycle driven by the `ProgramAdmin`. An active camera may be suspended, transitioning `ACTIVE → SUSPENDED`; a suspended camera may be reactivated, transitioning `SUSPENDED → ACTIVE`; and a camera may be decommissioned from either operational state, transitioning `ACTIVE → DECOMMISSIONED` or `SUSPENDED → DECOMMISSIONED`. `DECOMMISSIONED` is terminal. Each of these actions requires the camera to be in the stated originating state; attempting one from any other state is rejected with `ERR_INVALID_STATE`.

Certification is logged through **calibration records**. A `ProgramAdmin` files a calibration/certification for a camera by supplying `performed_at_utc` (when the work was done), `valid_until_utc` (when the certification expires), a `technician_ref` identifying the certifying technician, a `result` of exactly `PASS` or `FAIL`, and optional free-text `notes`. The expiry must be strictly after the performance time — `valid_until_utc` must be later than `performed_at_utc` — and a record that violates this ordering is rejected with `ERR_INVALID_REQUEST`. Filing a passing record refreshes the camera's `certified_until_clock` to the latest passing `valid_until_utc`. Calibration records are append-only audit entries and are never modified after creation.

### 3.2. Registered Owners and the Evidence Portal

A `ProgramAdmin` registers plate owners under a program. A **RegisteredOwner** is created with a `plate_number`, a `full_name`, and a `mailing_address`, and belongs to its program through `program_id`. The `plate_number` must be unique within its program; a duplicate registration is rejected with `ERR_DUPLICATE`. At registration the server mints a `portal_access_pin` for the owner — this is the credential the owner later presents, paired with their `registered_owner_id`, to authenticate in the evidence portal.

Through the portal, an owner can view their own citations and the associated evidence by presenting their `registered_owner_id` and `portal_access_pin`; results may be narrowed by citation `status`. This same PIN authentication is what allows an owner to file a contest, as described below. Any portal request whose owner identifier and PIN do not match is rejected with `ERR_PORTAL_AUTH_FAILED`.

### 3.3. Capturing and Reviewing a Violation

A violation enters the system when a `ReviewOfficer` or `ProgramAdmin` captures an event. The capture payload names the `program_id`, the capturing `camera_id`, the `captured_plate_number` read at the scene, the `event_at_utc` timestamp of the violation, and, for speed cameras, the `measured_speed_mph`. Capture is only permitted when the camera's `status` is `ACTIVE` at handling time; a capture against a non-active camera is rejected with `ERR_NO_VIOLATION` (HTTP 422). For a speed camera, the captured event is only a violation when `measured_speed_mph` is strictly greater than the camera's `speed_limit_mph`; if it is equal or lower, the capture is likewise rejected with `ERR_NO_VIOLATION`. A red-light capture carries no measured speed. A successful capture creates a **Citation** in `PENDING_REVIEW` status; at this point the citation's `registered_owner_id` is still null, and the money fields have not yet been computed.

A `ReviewOfficer` then reviews the pending citation and submits a `decision` of either `APPROVE` or `REJECT`. Both decisions require the citation to be in `PENDING_REVIEW`; otherwise the review is rejected with `ERR_INVALID_STATE`. On the review, whichever way it goes, the officer's `X-User-ID` is recorded on the citation as `review_officer_ref`.

A **rejection** moves the citation `PENDING_REVIEW → REJECTED`, which is terminal. No owner lookup is performed and no notice is issued for a rejected citation.

An **approval** is the pivotal transition and carries several preconditions and side effects. First, the capturing camera must have had valid calibration coverage at the moment of the violation: there must exist a `PASS` calibration record for that camera whose `performed_at_utc` is at or before the citation's `event_at_utc` and whose `valid_until_utc` is strictly after the `event_at_utc`. If no such passing coverage exists, the approval is rejected with `ERR_CALIBRATION_LAPSED` (HTTP 422). Second, the owner lookup must resolve: there must be a `RegisteredOwner` in this program whose `plate_number` equals the citation's `captured_plate_number`. If no such owner exists, the approval is rejected with `ERR_OWNER_LOOKUP_FAILED` (HTTP 422). When both hold, the approval transitions the citation `PENDING_REVIEW → CITED` and performs all of the following: it sets `registered_owner_id` to the matched owner's `id`; it sets `notice_issued_at_utc` to the current logical clock (the notice is now issued); it sets `due_at_utc` to the notice time plus the program's `response_window_days`; it computes `assessed_amount_cents` via the statutory fine schedule of Section 3.4; it sets `adjudicated_amount_cents` equal to `assessed_amount_cents` as the starting owed amount; it sets `escalation_stage` to `NONE`; and it appends a `NoticeRecord` of `notice_type` `INITIAL`, carrying the `registered_owner_id`, an `issued_at_clock` of now, and an `amount_owed_snapshot_cents` equal to the assessed amount.

A citation's `status` is one of `PENDING_REVIEW`, `REJECTED`, `CITED`, `CONTESTED`, `HEARING_SCHEDULED`, `ADJUDICATED_UPHELD`, `ADJUDICATED_DISMISSED`, `PAID`, `DELINQUENT`, or `VOID`. When a citation is read, the system surfaces its current total owed (see Section 3.6) alongside its stored fields, which include `camera_id`, `captured_plate_number`, `event_at_utc`, `measured_speed_mph`, `notice_issued_at_utc`, `due_at_utc`, `escalation_stage`, `assessed_amount_cents`, `adjudicated_amount_cents`, `amount_paid_cents`, and `review_officer_ref`.

### 3.4. The Statutory Fine Schedule

When a citation reaches `CITED`, its `assessed_amount_cents` is computed as follows, and the result is an integer number of cents throughout.

The base fine depends on the camera type. For a `RED_LIGHT` camera, the base is the program's `base_red_light_fine_cents`. For a `SPEED` camera, the base starts from the program's `base_speed_fine_cents` and is scaled by a band multiplier chosen from how far over the limit the driver was. Let the amount over be the citation's `measured_speed_mph` minus the camera's `speed_limit_mph` (this is guaranteed positive by the capture-time no-violation check). The band multiplier is selected by a single band, not by summing across bands: if the amount over is at most 10 mph, the multiplier is 1.0; if the amount over is at most 20 mph (that is, from 11 through 20 mph over), the multiplier is 1.5; and if the amount over is 21 mph or more, the multiplier is 2.5. The base for a speed violation is the `base_speed_fine_cents` multiplied by the selected multiplier, rounded half up to a whole cent.

Next, a repeat-offender surcharge may apply. The system counts the prior citations belonging to the *same* `registered_owner_id` in this same program whose `status` is any of `CITED`, `CONTESTED`, `HEARING_SCHEDULED`, `ADJUDICATED_UPHELD`, `PAID`, or `DELINQUENT`, and whose `notice_issued_at_utc` falls within the repeat-offender lookback measured backward from this citation's own notice time. The lookback window is half-open on its lower bound and inclusive on its upper bound: a prior notice counts when its notice time is strictly later than this citation's notice time minus `repeat_offender_window_days`, and at or before this citation's notice time. If that count is at least one, this is a repeat offense, and the base is multiplied by one plus the program's `repeat_offender_surcharge_pct`, rounded half up to a whole cent.

The two rounding steps are applied independently and in this exact order — first the speed-band multiply-and-round (for speed cameras), then, if applicable, the surcharge multiply-and-round — and are never combined into a single multiplication. Finally, the program's `admin_fee_cents` is added to the (possibly surcharged) base to produce `assessed_amount_cents`. The administrative fee is part of the assessed amount but is never itself subject to the band multiplier or the surcharge.

### 3.5. Contesting, Scheduling a Hearing, and Adjudication

A `RegisteredOwner` who disagrees with a citation may file a **Contest** through the portal. Filing authenticates with the owner's `registered_owner_id` and `portal_access_pin`, and the payload additionally carries the `ground`, a written `statement`, and `expected_citation_version`. The `ground` is exactly one of `NOT_THE_DRIVER`, `PLATE_MISREAD`, `SIGNAL_MALFUNCTION`, `CALIBRATION_LAPSED`, or `EMERGENCY`. A contest may be filed only while the citation is `CITED`; from any other state the filing is rejected with `ERR_INVALID_STATE`. The contest must also be timely: the current logical clock must be at or before the citation's `due_at_utc`; a filing after the due instant is rejected with `ERR_CONTEST_WINDOW_CLOSED` (HTTP 422). Because filing is OCC-guarded, `expected_citation_version` must match the citation's current `version`, or the filing is rejected with `ERR_STALE_VERSION` as described in Section 2.6. A successful filing transitions the citation `CITED → CONTESTED`, increments the citation's `version` by one, records the filer as `submitted_by_owner_id`, and creates a `Contest` in `SUBMITTED` status. A contest's `status` is one of `SUBMITTED`, `SCHEDULED`, `UPHELD`, `DISMISSED`, or `WITHDRAWN`.

A `ProgramAdmin` schedules a **Hearing** for a submitted contest. Scheduling requires the citation to be `CONTESTED` and the contest to be `SUBMITTED`; otherwise it is rejected with `ERR_INVALID_STATE`. The scheduling payload supplies `scheduled_at_utc` and the `adjudicator_ref` who will preside. The `scheduled_at_utc` must be strictly in the future relative to the logical clock at scheduling time; a non-future time is rejected with `ERR_HEARING_TIME_INVALID` (HTTP 422). The assigned `adjudicator_ref` must differ from the citation's `review_officer_ref`, enforcing separation of duties; equality is rejected with `ERR_SEGREGATION_OF_DUTIES`. A successful scheduling transitions the citation `CONTESTED → HEARING_SCHEDULED`, moves the contest `SUBMITTED → SCHEDULED`, and creates a `Hearing` in `SCHEDULED` status. A hearing carries `contest_id` and `citation_id`, and its `status` is one of `SCHEDULED`, `RULED`, or `ADJOURNED`.

An `Adjudicator` rules on a scheduled hearing by supplying an `outcome`, optionally a `reduced_amount_cents`, and the OCC field `expected_hearing_version`. Ruling requires the citation to be `HEARING_SCHEDULED` and the hearing to be `SCHEDULED`; otherwise it is rejected with `ERR_INVALID_STATE`. The hearing must actually have occurred: the current logical clock must be at or after the hearing's `scheduled_at_utc`, and a ruling attempted before that instant is rejected with `ERR_HEARING_TIME_INVALID`. The ruling adjudicator's `X-User-ID` must differ from the citation's `review_officer_ref` (`ERR_SEGREGATION_OF_DUTIES`), and `expected_hearing_version` must match the hearing's current `version` (`ERR_STALE_VERSION`). Every ruling transitions the hearing `SCHEDULED → RULED`, sets the hearing's `outcome`, and increments the hearing's `version` by one. The `outcome` is one of three values, and each drives a distinct citation resolution:

- **`UPHELD`**: the citation is liable at the full statutory amount. The citation transitions `HEARING_SCHEDULED → ADJUDICATED_UPHELD`, its `adjudicated_amount_cents` is set to its `assessed_amount_cents` (the fine stands unchanged, surcharge included), the hearing's `outcome` becomes `UPHELD`, and the contest moves `SCHEDULED → DISMISSED`.
- **`REDUCED`**: the adjudicator sets a reduced fine via `reduced_amount_cents`. This value must be present and strictly greater than zero and strictly less than the citation's `assessed_amount_cents` minus the program's `admin_fee_cents` (that is, strictly less than the statutory fine portion excluding the admin fee); a missing or out-of-range value is rejected with `ERR_INVALID_REDUCTION` (HTTP 422). On a valid reduction the citation transitions `HEARING_SCHEDULED → ADJUDICATED_UPHELD` (the owner remains liable, but at the reduced amount), the hearing's `outcome` becomes `REDUCED`, and the contest moves `SCHEDULED → DISMISSED`. The citation's `adjudicated_amount_cents` is recomputed as the adjudicator's `reduced_amount_cents` plus the program's `admin_fee_cents`. No repeat-offender surcharge is re-applied — the adjudicator's number is authoritative for the fine portion — so for identical inputs the reduced total is strictly less than the statutory total.
- **`DISMISSED`**: the citation is thrown out. The citation transitions `HEARING_SCHEDULED → ADJUDICATED_DISMISSED`, which is terminal, the hearing's `outcome` becomes `DISMISSED`, and the contest moves `SCHEDULED → UPHELD` (the contest is upheld because the citation is dismissed). As compensation, the citation's `adjudicated_amount_cents` is set to zero and its `escalation_stage` is set to `NONE`, so the owner owes nothing.

A hearing may also be forced out of `SCHEDULED` into `ADJOURNED` by a citation-void cascade, described in Section 3.8; that is the only other exit from `SCHEDULED`.

### 3.6. Amount Owed and the Delinquency Escalation

The total an owner must pay to bring a citation to `PAID` is derived from the citation's `adjudicated_amount_cents` and its current escalation. The owed total equals the `adjudicated_amount_cents`, plus — only when the citation's `escalation_stage` is `DELINQUENT` — a single flat `late_fee_cents` from the program, applied exactly once at the delinquent stage. A citation that has been dismissed on adjudication or voided has an `adjudicated_amount_cents` of zero and therefore owes zero. This owed total is what a citation read surfaces, what a payment is measured against, and what a delinquency notice snapshots.

Escalation itself is driven by a `SystemAdmin`-triggered escalation sweep, optionally scoped to a single `program_id`, which examines citations against the logical clock. A citation escalates to delinquency only once the clock has passed the delinquency deadline, which is the citation's `due_at_utc` plus one further `response_window_days` — in other words the clock must be strictly later than `due_at_utc` plus `response_window_days`. The sweep escalates a citation in either of two states: a `CITED` citation past that deadline transitions `CITED → DELINQUENT`, and an `ADJUDICATED_UPHELD` citation past that deadline transitions `ADJUDICATED_UPHELD → DELINQUENT`. In both cases the citation's `escalation_stage` becomes `DELINQUENT`, the `adjudicated_amount_cents` itself is left unchanged (the late fee enters through the owed-total calculation, not by mutating the adjudicated amount), and the sweep appends a `NoticeRecord` of `notice_type` `DELINQUENT` carrying the `registered_owner_id`, an `issued_at_clock` of now, and an `amount_owed_snapshot_cents` equal to the owed total at that instant (which now includes the late fee). A notice record's `notice_type` is exactly one of `INITIAL` or `DELINQUENT`.

### 3.7. Payments, Clearing, Vendor Revenue Share, and Reversal

Payment against a citation is initiated by a `ProgramAdmin` or by the `RegisteredOwner` (the latter authenticating with `registered_owner_id` and `portal_access_pin` on the payment). The payload carries the `amount_cents` tendered and a `method` of exactly `CARD`, `CHECK`, or `CASH`. The `amount_cents` must be greater than zero, and a payment may not be initiated against a citation that owes nothing — one that is `VOID`, `ADJUDICATED_DISMISSED`, or already `PAID` — with either violation rejected as `ERR_NOTHING_OWED` (HTTP 422). A successful initiation creates a `Payment` in `INITIATED` status; a payment's `status` is one of `INITIATED`, `CLEARED`, `FAILED`, or `REVERSED`.

Payment settlement is simulated by a `SystemAdmin` callback that names the `payment_id` and an `outcome`. Settling with a failing outcome transitions the payment `INITIATED → FAILED` with no further effect. Settling with a clearing outcome transitions the payment `INITIATED → CLEARED` and recomputes the citation's `amount_paid_cents` as the sum of all cleared payments against that citation. If the cumulative cleared amount then meets or exceeds the citation's current owed total, the citation transitions to `PAID`. This clearing-to-`PAID` transition is defined from `CITED`, from `ADJUDICATED_UPHELD`, and from `DELINQUENT`; reaching `PAID` from any of those states recomputes `amount_paid_cents` and accrues the vendor revenue share described next.

The vendor revenue share attaches only when a citation reaches `PAID`, and only to the fine portion actually collected — never to the administrative fee and never to any late fee. The share is computed against the single `ACTIVE` `VendorContract` of the citation's program; a program has exactly one active contract at a time, and if a stale active contract also exists, the most recently created active one (by `created_at` ascending, taking the last) is authoritative. A vendor contract is created by a `ProgramAdmin` with a `vendor_name`, a `revenue_share_pct` between 0 and 1 expressing the vendor's fraction of net collected fine revenue, and an optional `monthly_cap_cents`; it begins `ACTIVE` and may be terminated to `TERMINATED`. The fine portion for the share is the citation's `adjudicated_amount_cents` minus the program's `admin_fee_cents` (never below zero). The raw share is that fine portion multiplied by the contract's `revenue_share_pct`, rounded half up to a whole cent. If the contract has a `monthly_cap_cents`, the accrual may not push the contract's running `accrued_vendor_share_cents` above the cap: the applied share is the lesser of the raw share and the remaining headroom, where headroom is the cap minus the already-accrued amount, floored at zero. If there is no cap, the applied share is the raw share. On reaching `PAID`, the applied share is added to the contract's `accrued_vendor_share_cents`, which is surfaced for audit and never goes below zero.

A cleared payment may be reversed by a `ProgramAdmin`. Reversal requires the payment to be `CLEARED` and transitions it `CLEARED → REVERSED`. It recomputes the citation's `amount_paid_cents` downward. If the citation had reached `PAID`, reversal is a compensation cascade: the citation is reverted to the owed state it held before payment — to `ADJUDICATED_UPHELD` if it had a ruling, otherwise to `CITED` — and the vendor share that was accrued for this citation is de-accrued by exactly the same amount that was previously added, with the contract's `accrued_vendor_share_cents` floored at zero.

### 3.8. Voiding a Citation and Its Cascade

A `ProgramAdmin` may void a citation. A void is permitted only while the citation is in `PENDING_REVIEW`, `CITED`, or `DELINQUENT`; from any other state it is rejected with `ERR_INVALID_STATE`. Additionally, a void is refused if any cleared payment exists against the citation, rejected with `ERR_PAYMENT_EXISTS` (HTTP 409). A successful void transitions the citation to `VOID`, which is terminal, and sets its `adjudicated_amount_cents` to zero so that nothing is owed. The void then cascades to any open contest and hearing on that citation: a contest in `SUBMITTED` or `SCHEDULED` is moved to `WITHDRAWN`, and a hearing in `SCHEDULED` is moved to `ADJOURNED`. This is why an adjudicator who loaded a hearing before a void may find their ruling rejected on the stale-version check — the void bumped the hearing's `version`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify or act on an existing resource, and the internal test-driving operations, return `200 OK`. All list and single-read operations return `200 OK`. The request body, response body, and side effects of each operation are described in Section 3; the table below is only an index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/programs` | Create an enforcement program | SystemAdmin |
| GET | `/programs/{pid}` | Get a program | SystemAdmin, ProgramAdmin, ReviewOfficer, Adjudicator, Auditor |
| GET | `/programs` | List programs | SystemAdmin, Auditor |
| POST | `/cameras` | Register a camera under a program | ProgramAdmin |
| GET | `/cameras/{id}` | Get a camera | ProgramAdmin, ReviewOfficer, Auditor |
| GET | `/cameras` | List cameras (filterable) | ProgramAdmin, ReviewOfficer, Auditor |
| POST | `/cameras/{id}/suspend` | Suspend a camera | ProgramAdmin |
| POST | `/cameras/{id}/reactivate` | Reactivate a suspended camera | ProgramAdmin |
| POST | `/cameras/{id}/decommission` | Decommission a camera | ProgramAdmin |
| POST | `/cameras/{id}/calibrations` | Log a calibration/certification record | ProgramAdmin |
| GET | `/cameras/{id}/calibrations` | List calibration records for a camera | ProgramAdmin, ReviewOfficer, Auditor |
| POST | `/owners` | Register a plate owner (mints portal PIN) | ProgramAdmin |
| GET | `/owners/{id}` | Get a registered owner | ProgramAdmin, Auditor |
| GET | `/owners` | List/search registered owners | ProgramAdmin, Auditor |
| POST | `/citations` | Capture a violation event | ReviewOfficer, ProgramAdmin |
| GET | `/citations/{id}` | Get a citation (owed total surfaced) | ProgramAdmin, ReviewOfficer, Adjudicator, Auditor |
| GET | `/citations` | List citations (filterable) | ProgramAdmin, ReviewOfficer, Adjudicator, Auditor |
| POST | `/citations/{id}/review` | Approve or reject a pending citation | ReviewOfficer |
| POST | `/citations/{id}/void` | Void a citation (cascades) | ProgramAdmin |
| POST | `/citations/{id}/contests` | Owner files a contest via portal | RegisteredOwner |
| GET | `/citations/{id}/contests` | List contests of a citation | ProgramAdmin, Adjudicator, Auditor |
| GET | `/contests/{id}` | Get a contest | ProgramAdmin, Adjudicator, Auditor |
| GET | `/owners/{id}/contests` | List contests filed by an owner | ProgramAdmin, Auditor |
| POST | `/contests/{id}/hearings` | Schedule a hearing and assign adjudicator | ProgramAdmin |
| GET | `/contests/{id}/hearings` | List hearings for a contest | ProgramAdmin, Adjudicator, Auditor |
| GET | `/hearings/{hid}` | Get a hearing | ProgramAdmin, Adjudicator, Auditor |
| GET | `/citations/{id}/hearings` | List hearings for a citation | ProgramAdmin, Adjudicator, Auditor |
| POST | `/hearings/{hid}/rule` | Adjudicator rules on a hearing | Adjudicator |
| POST | `/citations/{id}/payments` | Initiate a payment against a citation | ProgramAdmin, RegisteredOwner |
| GET | `/citations/{id}/payments` | List payments for a citation | ProgramAdmin, Auditor, RegisteredOwner |
| POST | `/payments/{id}/reverse` | Reverse a cleared payment (compensation) | ProgramAdmin |
| POST | `/vendor-contracts` | Create a vendor contract under a program | ProgramAdmin |
| GET | `/vendor-contracts` | List vendor contracts (filterable) | ProgramAdmin, Auditor |
| GET | `/vendor-contracts/{id}` | Get a vendor contract | ProgramAdmin, Auditor |
| POST | `/vendor-contracts/{id}/terminate` | Terminate a vendor contract | ProgramAdmin |
| GET | `/citations/{id}/notices` | List notice/audit records for a citation | ProgramAdmin, Auditor |
| GET | `/owners/{id}/notices` | List notice/audit records mailed to an owner | ProgramAdmin, Auditor |
| GET | `/portal/citations` | Owner views own citations + evidence (portal PIN) | RegisteredOwner |
| POST | `/_clock/set_current_utc` | Set the server logical clock | SystemAdmin |
| POST | `/_payments/settle` | Settle an initiated payment to CLEARED or FAILED | SystemAdmin |
| POST | `/_escalation/sweep` | Escalate past-deadline citations to DELINQUENT | SystemAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_PORTAL_AUTH_FAILED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE` | 409 |
| `ERR_PAYMENT_EXISTS` | 409 |
| `ERR_CALIBRATION_LAPSED` | 422 |
| `ERR_NO_VIOLATION` | 422 |
| `ERR_OWNER_LOOKUP_FAILED` | 422 |
| `ERR_CONTEST_WINDOW_CLOSED` | 422 |
| `ERR_HEARING_TIME_INVALID` | 422 |
| `ERR_INVALID_REDUCTION` | 422 |
| `ERR_NOTHING_OWED` | 422 |
| `ERR_INVALID_REQUEST` | 422 |

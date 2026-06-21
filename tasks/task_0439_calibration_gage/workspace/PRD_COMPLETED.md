# Calibration & Gage Management API — Product Requirements Document

## 1. Introduction

Manufacturing quality programs live or die by the trustworthiness of their measuring instruments. A caliper that has silently drifted out of tolerance does not merely produce a bad reading — it casts doubt on every product that instrument has touched since its last good calibration. This API is the system of record for that trust chain. It maintains an asset register of instruments and the reference standards they are calibrated against, schedules and records calibration events, and traces each standard back through a chain of higher standards to a National Institute of Standards and Technology (NIST) anchor.

The platform is deliberately built around the consequences of a failed calibration rather than the happy path. When an instrument is found out of tolerance, the system quarantines it, opens an out-of-tolerance impact investigation, and helps quality staff identify and recall the products that were measured during the suspect window. Alongside this, it supports external calibration vendors and their certificates, gage repeatability-and-reproducibility (R&R) studies that quantify a measurement system's variation, and drift-trend analytics that project when an instrument will breach tolerance. Because metrology results must withstand audit, the system enforces strict segregation of duties: the technician who runs a calibration is never the quality engineer who dispositions its fallout, and certificate verification is reserved for a separate metrologist.

Time in this system is logical, not wall-clock. A single advancing epoch counter drives every "due", "overdue", "expired", and "currently traceable" determination, so that calibration intervals and certification validity can be tested deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is absent or empty, the request is rejected with `ERR_MISSING_USER_CONTEXT`. The system recognizes exactly three roles: `Technician`, `QualityEngineer`, and `Metrologist`. When the supplied role is not one of these three, or is one of them but is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The three roles divide the work along quality-assurance lines. A `Technician` performs calibrations — opening calibration events, recording measurement points, and starting, finalizing, reopening, or cancelling those events. A `QualityEngineer` owns the asset register and the out-of-tolerance impact lifecycle — registering, releasing, and retiring instruments, investigating, dispositioning, escalating, and cancelling impacts, attaching affected products, running gage R&R studies, and advancing the logical clock. A `Metrologist` owns reference standards, vendors, and certificates — registering and updating standards and vendors, and issuing, verifying, rejecting, and reissuing certificates. Read (GET) endpoints are available to all three roles, and recording an individual gage R&R trial cell is open to both `Technician` and `QualityEngineer`.

For all three roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it where a workflow demands it — for example, a calibration event stores the acting technician's identifier in its `performed_by_user_id` field, and an out-of-tolerance impact stores the acting engineer's identifier in `dispositioned_by_user_id` when it is dispositioned — but the server never compares `X-User-ID` to any entity's `id`. Where segregation of duties applies, the comparison is between two recorded operator identifiers (the disposition actor versus the event author), never between an identifier and an entity primary key.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts values from a minimum of 1 to a maximum of 100 — a supplied `limit` that is not an integer, or that falls below 1 or above 100, is rejected with `ERR_INVALID_REQUEST` (HTTP 422) rather than clamped. The `offset` parameter skips a number of leading items and defaults to 0; a supplied `offset` that is not an integer or is negative is likewise rejected with `ERR_INVALID_REQUEST`.

Unless an endpoint states otherwise, list results are sorted by their `created_at` timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in the system carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits set at creation, and `updated_at` is the same format, refreshed on every mutation. The `version` field is an integer that begins at its initial value and increments by one on every mutation of the resource; it is the basis for optimistic concurrency control described in §2.7. These four fields are present on every entity except the singleton clock.

The one exception is `ClockState`, the logical clock. It carries only an `id` and a `created_at`; it has neither an `updated_at` nor a `version`. Its single meaningful field is `current_epoch`, an integer counter. The server boots with `current_epoch` equal to 0, which by definition maps to the default instant of 2026-01-01T00:00:00Z UTC. The clock never reads wall-clock time; `current_epoch` advances only when an explicit clock-advance capability is invoked with a `by_epochs` increment. Every notion of "due", "overdue", "certified through", and "accredited through" in this system is measured against `current_epoch`.

### 2.5. Hierarchical Consistency and Nested Resource Retrieval

The entity graph is layered: instruments own calibration events and gage R&R studies; calibration events own measurement points and certificates; out-of-tolerance impacts own affected products; gage R&R studies own trials. For any request whose path names more than one resource, the server validates path identifiers strictly left to right and rejects with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve. A measurement point requested under a non-existent calibration event fails on the event before the point is ever consulted.

Many operations mutate more than one entity. Whenever the server changes a resource — whether through a direct client action or an automatic reconciliation it performs itself — it refreshes that resource's `updated_at` and increments its `version`. State that propagates from a child to its parent (for example, finalizing a calibration event that changes the owning instrument's calibration status) mutates both the child and the parent, and each mutated entity's `version` advances by one independently. The specific cascades are described in the workflow narratives of §3; the invariant here is simply that every entity touched by an operation has its `version` and `updated_at` advanced.

### 2.6. Precision and Rounding

Numeric results are reported to fixed precision. Test Uncertainty Ratio (`tur`) is rounded to 2 decimal places using round-half-up. The gage R&R percentage (`pct_grr`) is rounded to 2 decimal places round-half-up, and the displayed standard-deviation estimates `ev_repeatability`, `av_reproducibility`, and `grr` are stored at 6 decimal places round-half-up. The maximum absolute deviation (`max_abs_deviation`) of a calibration event is rounded to 6 decimal places round-half-up, and the drift `slope` is rounded to 6 decimal places round-half-up. Epoch-valued results — `next_due_epoch`, `last_calibration_epoch`, suspect-window bounds, the projected breach epoch, and all product and exposure counts — are integers. Where a calculation prescribes a specific order of rounding (notably the gage R&R chain), that order is part of the contract and is detailed in §3.

### 2.7. Optimistic Concurrency Control

Two creation operations are guarded against stale writes on their parent instrument. Opening a new calibration event under an instrument requires the request body to carry `expected_instrument_version`, and that value must equal the target instrument's current `version`. If another writer has advanced the instrument's version since the client last observed it — for instance by finalizing a prior event, which bumps the instrument's version and changes its calibration status and next-due epoch — the create is rejected with `ERR_STALE_INSTRUMENT_VERSION` (HTTP 412), preventing the client from opening a calibration against an instrument view it has not actually seen.

The same guard protects creating a gage R&R study under an instrument: the request must carry `expected_instrument_version` matching the instrument's current `version`, and a mismatch is rejected with `ERR_STALE_INSTRUMENT_VERSION` (HTTP 412). This matters because another writer may have just retired or quarantined the instrument — each of which advances its version — so a study created from a stale view would attach to an instrument that is no longer eligible. No other endpoint takes a version field; the OCC field is required exactly on these two creates and nowhere else.

### 2.8. Traceability to NIST

A reference standard is itself a calibrated asset that must trace, through a chain of progressively higher standards, back to a NIST anchor. Each `CalibrationStandard` may name a `parent_standard_id` pointing at a higher standard. When `parent_standard_id` is null, the standard is the anchor traced directly to NIST, and `nist_test_number` carries its NIST traceability test number; an empty `nist_test_number` is permitted only when a `parent_standard_id` is set. The computed `traceability_depth` is 0 at the anchor and is one greater than the parent's depth at every other node.

The chain forms a directed acyclic graph, and the server protects it at write time. On registering or updating a standard, if following `parent_standard_id` links would form a cycle, would make the standard its own ancestor, or would produce a chain deeper than the maximum of 10 links, the write is rejected with `ERR_TRACEABILITY_CYCLE` (HTTP 409). The computed `is_traceable` flag is true only when every standard on the path from the leaf up to and including the anchor is in `ACTIVE` status and has a `certified_through_epoch` greater than or equal to the clock's `current_epoch`. A single expired or retired link anywhere on the path renders the leaf not traceable.

### 2.9. Vendor Accreditation

External calibrations may be performed by a `CalibrationVendor`, an accredited laboratory. A vendor's `accreditation_body` is one of `A2LA`, `NVLAP`, `UKAS`, or `NONE`, and its `accreditation_number` must be non-empty unless the body is `NONE`. The computed `is_accreditation_current` flag is true only when the body is not `NONE` and the vendor's `accredited_through_epoch` is greater than or equal to the clock's `current_epoch`. A vendor's `status` is either `ACTIVE` or `SUSPENDED`. Vendor eligibility — an `ACTIVE` status together with current accreditation — gates both starting an externally-performed calibration event and verifying a certificate, as detailed in §3.

### 2.10. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority order so that the same failing request always yields the same error. Authentication comes first: the presence of `X-User-ID` and `X-User-Role` (`ERR_MISSING_USER_CONTEXT`) is checked before the role's permission to perform the operation (`ERR_FORBIDDEN_ROLE`). Next, existence is resolved: path identifiers are validated left to right (`ERR_NOT_FOUND`), then body foreign keys such as `standard_id`, `vendor_id`, and `parent_standard_id` are confirmed to reference existing rows (`ERR_FK_NOT_FOUND`). After existence comes request well-formedness — required fields present and correctly typed, enum members valid, and numeric ranges satisfied such as non-negative tolerances and counts within their stated bounds (`ERR_INVALID_REQUEST`, HTTP 422). Uniqueness and referential business rules follow — duplicate asset tag (`ERR_DUPLICATE_ASSET_TAG`), duplicate certificate number (`ERR_DUPLICATE_CERTIFICATE_NUMBER`), traceability cycle (`ERR_TRACEABILITY_CYCLE`). Only then are state-machine and business-safety rules evaluated: that the resource is in a state from which the transition is defined (`ERR_INVALID_STATE`), that the owning instrument is `ACTIVE` where required (`ERR_INSTRUMENT_NOT_ACTIVE`) or at least not `RETIRED` (`ERR_INSTRUMENT_RETIRED`), and the remaining domain guards described throughout §3. In short: authentication, then authorization, then path existence, then foreign-key existence, then request validity, then uniqueness, then state, then business safety.

## 3. Business Logic & Workflows

### 3.1. The Asset Register: Registering and Retiring Instruments

A `QualityEngineer` brings an instrument into the register by supplying its human-readable `asset_tag`, a `description`, the `nominal_value` that serves as its tolerance reference, the upper and lower tolerance offsets `tolerance_plus` and `tolerance_minus` (each of which must be non-negative), the `measurement_unit` those values are expressed in, the `calibration_interval_epochs` between scheduled calibrations (which must be at least 1), and a `criticality` of `CRITICAL`, `MAJOR`, or `MINOR`. The asset tag must be unique among instruments whose `lifecycle_status` is not `RETIRED`; a collision is rejected with `ERR_DUPLICATE_ASSET_TAG`. A freshly registered instrument starts with `lifecycle_status` of `ACTIVE` and `calibration_status` of `UNCALIBRATED`, and its open-impact counter `open_oot_count` begins at 0.

An instrument carries two independent state axes on the same record. The `lifecycle_status` axis tracks availability and moves among `ACTIVE`, `QUARANTINED`, and `RETIRED`; `RETIRED` is the only terminal condition. The `calibration_status` axis is derived from calibration history and clock position and takes the values `UNCALIBRATED`, `IN_TOLERANCE`, `OUT_OF_TOLERANCE`, and `OVERDUE`; it has no terminal of its own. The two computed scheduling fields, `last_calibration_epoch` and `next_due_epoch`, are null until the instrument's first successful calibration.

Releasing a quarantined instrument is a `QualityEngineer` action that returns `lifecycle_status` from `QUARANTINED` to `ACTIVE`. It is permitted only when the instrument is currently `QUARANTINED` (otherwise `ERR_INVALID_STATE`), when `open_oot_count` is 0 — meaning every out-of-tolerance impact for the instrument has reached `DISPOSITIONED` or `CANCELLED` (otherwise `ERR_OPEN_IMPACT_EXISTS`) — and when the latest finalized calibration event for the instrument — the finalized event (one whose status is `PASSED`, `CONDITIONAL_PASS`, or `FAILED`) with the greatest `scheduled_epoch`, breaking ties toward the later `created_at` — has a result of `PASS` or `CONDITIONAL` (otherwise `ERR_LATEST_CAL_NOT_PASSING`). A successful release sets `lifecycle_status` to `ACTIVE` and increments the instrument's version.

Retiring an instrument is the terminal `QualityEngineer` action, moving `lifecycle_status` from either `ACTIVE` or `QUARANTINED` to `RETIRED`. It is blocked while any calibration event for the instrument is still in `DRAFT` or `IN_PROGRESS` (rejected with `ERR_OPEN_CALIBRATION_EXISTS`) and while `open_oot_count` is greater than 0 (rejected with `ERR_OPEN_IMPACT_EXISTS`). Once retired, the instrument's asset tag is no longer reserved and may be reused by a new instrument. Both release and retire are write operations against the instrument and both increment its version; neither, however, is an OCC-guarded create, so neither takes an `expected_instrument_version` field. Any write directed at a `RETIRED` instrument or its children is refused with `ERR_INSTRUMENT_RETIRED`.

### 3.2. Reference Standards and External Vendors

A `Metrologist` registers a `CalibrationStandard` by supplying its `name`, its `nist_test_number`, an optional `parent_standard_id`, the certified `nominal_value` with its `standard_unit`, the expanded calibration `uncertainty` (which is reported at coverage factor k=2 and must be non-negative), and the `certified_through_epoch` through which the standard's own calibration remains valid. At creation the server computes `traceability_depth`, `is_traceable`, and assigns a `status` of `ACTIVE` (the alternative being `RETIRED`), all as described in §2.8. Updating a standard may change its `parent_standard_id`, `certified_through_epoch`, `uncertainty`, or `status`, after which the server recomputes `traceability_depth` and `is_traceable` for that standard and re-validates the traceability graph. Standards may be listed with the parent filter `parent_standard_id` to walk the children of a given node.

A `Metrologist` also registers a `CalibrationVendor` by supplying its `name`, its `accreditation_body`, an `accreditation_number` (required unless the body is `NONE`), and its `accredited_through_epoch`; the server computes `is_accreditation_current` and assigns an initial `status` of `ACTIVE`. The accreditation expiry or the body may later be updated, supplying `accredited_through_epoch` and `status` (the latter being `ACTIVE` or `SUSPENDED`), after which `is_accreditation_current` is recomputed. The eligibility rule that ties these fields to calibration work lives in §3.3 and §3.6.

### 3.3. Performing a Calibration: Events and Measurement Points

A `Technician` opens a calibration against an instrument, which creates a `CalibrationEvent` in `DRAFT`. The create body carries the `standard_id` of the reference standard to be used (the traceability link for this event), an optional `vendor_id` (null for an in-house calibration, set for an external one), the `scheduled_epoch` at which the calibration is performed, and the `expected_instrument_version` that arms the optimistic-concurrency guard of §2.7. The server stamps the event's `instrument_id` from the path, records the acting technician's identifier in `performed_by_user_id`, and — because registering calibration activity mutates the instrument's calibration record and advances the OCC guard — increments the instrument's version by one.

Before measurements can be recorded the event must hold at least one measurement point. A `Technician` adds a `MeasurementPoint` to a `DRAFT` or `IN_PROGRESS` event by supplying a `point_label`, the point's `nominal` target, its tolerance offsets `tol_plus` and `tol_minus` (each non-negative), the `as_found_value` read before any adjustment, and an optional `as_left_value` read after adjustment. When `as_left_value` is omitted it defaults to the `as_found_value`, signifying that no adjustment was made. Each point also exposes its owning `calibration_event_id`. The server immediately computes two pass flags for the point using a closed interval: `as_found_pass` is true exactly when the as-found reading is at least the nominal minus the lower tolerance and at most the nominal plus the upper tolerance, and `as_left_pass` applies the same closed-interval test to the as-left reading.

Starting an event advances it from `DRAFT` to `IN_PROGRESS` and is gated by four conditions. The owning instrument must be `ACTIVE` (otherwise `ERR_INSTRUMENT_NOT_ACTIVE`); the event must already have at least one measurement point (otherwise `ERR_NO_MEASUREMENT_POINTS`); the `standard_id` must resolve to a standard whose `is_traceable` is true at the moment of the start (otherwise `ERR_STANDARD_NOT_TRACEABLE`); and when a `vendor_id` is set, that vendor must be `ACTIVE` with `is_accreditation_current` true (otherwise `ERR_VENDOR_NOT_ELIGIBLE`). A successful start sets `status` to `IN_PROGRESS` and increments the event's version. A `DRAFT` event may instead be cancelled by a `Technician`, which is permitted only from `DRAFT` (otherwise `ERR_INVALID_STATE`); cancellation sets `status` to `CANCELLED`, a terminal state, and increments the event's version.

### 3.4. Finalizing a Calibration: Result Determination and Cascades

Finalizing an `IN_PROGRESS` event is the pivotal `Technician` action. At finalize the server computes, in order, the per-event diagnostics and the result. It first determines the as-found and as-left aggregate flags: `as_found_in_tolerance` is true exactly when every measurement point has `as_found_pass` true, and `as_left_in_tolerance` is true exactly when every point has `as_left_pass` true. It computes `max_abs_deviation` as the largest value, over the event's measurement points, of the absolute difference between a point's `as_found_value` and its `nominal`, reported to 6 decimal places round-half-up; this figure feeds the drift trend of §3.8.

The Test Uncertainty Ratio (`tur`) is computed from the instrument's tolerance band and the standard's uncertainty. The tolerance band width is the sum of the instrument's `tolerance_plus` and `tolerance_minus`. When the standard's `uncertainty` is exactly zero the ratio is treated as infinite (and therefore as meeting the minimum), and the event's stored `tur` field is serialized as `null` in that case; otherwise `tur` is the tolerance band width divided by twice the standard's `uncertainty`, reported to 2 decimal places round-half-up.

The result is then determined as a base outcome, possibly downgraded for insufficient measurement capability. The base outcome is `PASS` when every point passes both as-found and as-left; it is `CONDITIONAL` when at least one point fails as-found but every point passes as-left (the instrument was adjusted into tolerance); and it is `FAIL` when at least one point fails as-left. The capability gate is the minimum acceptable Test Uncertainty Ratio of 4.0: if `tur` is below 4.0 and the base outcome is not already `FAIL`, the result is forced to `FAIL`, because the measurement system cannot resolve the tolerance well enough to certify the instrument; otherwise the result is the base outcome. The computed `result` is one of `PASS`, `CONDITIONAL`, or `FAIL`.

A `PASS` or `CONDITIONAL` result moves the event to `PASSED` or `CONDITIONAL_PASS` respectively — both terminal — and cascades to the instrument: provided the instrument is not `RETIRED` (otherwise the finalize is refused with `ERR_INSTRUMENT_RETIRED`), the instrument's `calibration_status` becomes `IN_TOLERANCE` and its scheduling fields are recomputed (see below), advancing the instrument's version. A `FAIL` result is permitted only while the instrument is `ACTIVE` (otherwise `ERR_INSTRUMENT_NOT_ACTIVE`) and triggers a two-hop cascade: the event moves to `FAILED`, the instrument's `calibration_status` becomes `OUT_OF_TOLERANCE` and its `lifecycle_status` becomes `QUARANTINED`, an `OutOfToleranceImpact` is auto-created in `OPEN` with its `triggering_event_id` set to this event and its suspect window computed (see §3.5), `open_oot_count` is increased by one, and the instrument's version is incremented. In every finalize path the event's own version is also incremented.

The scheduling recomputation that follows a passing finalize, and that also runs during the recall sweep, must be evaluated in a pinned order rather than as a simultaneous equation. First, `last_calibration_epoch` is set to the greatest `scheduled_epoch` among the instrument's events whose result is `PASS` or `CONDITIONAL`, breaking ties toward the earlier `created_at`. Second, `next_due_epoch` is set to that `last_calibration_epoch` plus the instrument's `calibration_interval_epochs`. Third, the overdue flag is derived from the freshly computed `next_due_epoch` and the clock — never the reverse — so that an instrument is overdue exactly when `next_due_epoch` is not null and is strictly less than the clock's `current_epoch`. Fourth, `calibration_status` becomes `OVERDUE` only when that overdue condition holds and the instrument is `ACTIVE` and its current `calibration_status` is `IN_TOLERANCE`. The third step must read the `next_due_epoch` produced by the second step within the same finalize or sweep, never a stale persisted value.

A `FAILED` event is not the end of the road: it may be reopened back to `IN_PROGRESS` for re-measurement, forming a revision cycle. Reopening is a `Technician` action permitted only when the auto-created impact for this event has reached `CANCELLED` (otherwise `ERR_IMPACT_NOT_CANCELLED`) and the owning instrument is `QUARANTINED` (otherwise `ERR_INVALID_STATE`); it sets `status` to `IN_PROGRESS`, clears `result` back to null, and increments the event's version.

### 3.5. Out-of-Tolerance Impact and Product Recall

When a calibration fails, the auto-created `OutOfToleranceImpact` is the investigation record for everything the suspect instrument may have mismeasured. Its `instrument_id` and `triggering_event_id` are stamped by the server. Its suspect window is computed chronologically: `prior_calibration_epoch` is the greatest `scheduled_epoch` among the instrument's events whose result is `PASS` or `CONDITIONAL` and whose `scheduled_epoch` is strictly less than the triggering event's `scheduled_epoch` (ties broken toward the earlier `created_at`), or null when no such prior good calibration exists. The `suspect_window_start_epoch` is that `prior_calibration_epoch` when it is non-null, and otherwise 0 (the epoch the system associates with the instrument's creation, which is always 0 since instrument creation does not record a per-instrument creation epoch). The `suspect_window_end_epoch` is the triggering event's `scheduled_epoch`. The impact also exposes the running counts `affected_product_count` and `recalled_product_count`, both starting at 0.

A `QualityEngineer` enumerates the suspect products by attaching `AffectedProduct` records, each carrying a `product_serial` and the `measured_epoch` at which that product was measured by the instrument; the server stamps each record's owning `impact_id` from the path. On attach, the server sets `affected_product_count` up by one and computes `in_suspect_window`, which is true exactly when `measured_epoch` is at least `suspect_window_start_epoch` and at most `suspect_window_end_epoch` (a closed interval). An affected product begins in `FLAGGED` status and may later become `RECALLED` or `CLEARED`.

The impact lifecycle is a branching machine. From `OPEN` a `QualityEngineer` investigates it into `INVESTIGATING`, but only from `OPEN` (otherwise `ERR_INVALID_STATE`) and only when the acting `X-User-ID` differs from the triggering event's `performed_by_user_id` — the technician who ran the failed calibration may not investigate its fallout (otherwise `ERR_SEGREGATION_OF_DUTIES`, HTTP 403). From `INVESTIGATING` the engineer dispositions the impact, supplying a `disposition` of `USE_AS_IS`, `REWORK`, `RECALL`, or `SCRAP`; this is permitted only from `INVESTIGATING` (otherwise `ERR_INVALID_STATE`) and again enforces that the acting `X-User-ID` differs from the triggering event's `performed_by_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`). When the chosen disposition is `RECALL`, there must be at least one attached affected product whose `in_suspect_window` is true (otherwise `ERR_NO_RECALLABLE_PRODUCT`).

Disposition records the chosen `disposition`, stamps `dispositioned_by_user_id` from the acting identifier, moves the impact to `DISPOSITIONED` (terminal), and decrements the instrument's `open_oot_count` by one. The product-side effect diverges by branch. A `RECALL` disposition moves every affected product whose `in_suspect_window` is true to `RECALLED` and recomputes `recalled_product_count`. A `USE_AS_IS`, `REWORK`, or `SCRAP` disposition instead moves every `FLAGGED` affected product to `CLEARED`. Either way the impact's version increments.

Two other transitions complete the machine. From `INVESTIGATING` the engineer may escalate the impact to `ESCALATED`, a non-terminal hold, permitted only from `INVESTIGATING` (otherwise `ERR_INVALID_STATE`); an `ESCALATED` impact may be returned to `INVESTIGATING` for re-disposition, permitted only from `ESCALATED` (otherwise `ERR_INVALID_STATE`). Finally, an `OPEN` impact may be cancelled to `CANCELLED` (terminal), but only from `OPEN` (otherwise `ERR_INVALID_STATE`) and only when no affected product has already reached `RECALLED` (otherwise `ERR_RECALL_ALREADY_ISSUED`); cancelling also decrements the instrument's `open_oot_count` by one and increments the impact's version. The cancel path is what unblocks reopening the triggering event described in §3.4.

The persisted `recalled_product_count` written on a `RECALL` disposition counts affected products on the conservative basis: every affected product whose `measured_epoch` falls within the closed suspect window from `suspect_window_start_epoch` through `suspect_window_end_epoch`. A separate read-only exposure analytic offers the same count under either of two bases, selected by the `basis` query parameter whose only accepted values are `CONSERVATIVE` and `MEASURED` (any other supplied value is rejected with `ERR_INVALID_REQUEST`, HTTP 422). The conservative basis (`CONSERVATIVE`, the default when the parameter is omitted, and the one persisted on recall) counts all affected products whose `measured_epoch` lies in that closed window. The measured basis counts only affected products whose `measured_epoch` is strictly greater than `prior_calibration_epoch` and at most the suspect-window end — a half-open window that excludes any product measured exactly at the prior good calibration, on the reasoning that such a product was conforming; when `prior_calibration_epoch` is null the half-open lower bound is taken as `suspect_window_start_epoch` minus one, so the measured count coincides with the conservative count. The measured count is therefore always at most the conservative count. The exposure read reports the chosen `basis` as `exposure_count`, alongside the `basis` itself and the window bounds `suspect_window_start_epoch` and `suspect_window_end_epoch`.

### 3.6. Certificates and Verification

For an externally calibrated event, a `Metrologist` issues a `CalibrationCertificate` documenting it. The issue body carries the issuing `vendor_id`, a `certificate_number`, and the `issued_epoch`; the server records the owning `calibration_event_id` and sets `status` to `ISSUED`. A certificate number must be unique among the vendor's certificates whose status is not `REJECTED`; a collision is rejected with `ERR_DUPLICATE_CERTIFICATE_NUMBER`.

A certificate moves through a small branching machine with a revert. From `ISSUED` a `Metrologist` verifies it to `VERIFIED` (terminal), which requires that the owning calibration event be in `PASSED` or `CONDITIONAL_PASS` (otherwise `ERR_EVENT_NOT_FINALIZED`), that the certificate's `vendor_id` equal the owning event's `vendor_id` (otherwise `ERR_CERT_VENDOR_MISMATCH`), and that the issuing vendor's `is_accreditation_current` be true (otherwise `ERR_VENDOR_NOT_ELIGIBLE`). From `ISSUED` the metrologist may instead reject the certificate to `REJECTED`, permitted only from `ISSUED` (otherwise `ERR_INVALID_STATE`); rejection frees the certificate number for reuse. A `REJECTED` certificate may be reissued back to `ISSUED`, permitted only from `REJECTED` (otherwise `ERR_INVALID_STATE`) and supplying an optional replacement `certificate_number` that must again be unique among the vendor's non-`REJECTED` certificates (otherwise `ERR_DUPLICATE_CERTIFICATE_NUMBER`). Every certificate transition increments the certificate's version.

### 3.7. Measurement-System Capability: Gage R&R Studies

A `QualityEngineer` evaluates how much of an instrument's measured variation comes from the measurement system itself by running a gage R&R study against an `ACTIVE` instrument. Creating a `GageRRStudy` records the design parameters: `operator_count` (between 2 and 4 inclusive), `part_count` (between 2 and 10 inclusive), `trial_count` (between 2 and 4 inclusive), and the total `process_tolerance` used as the percentage denominator (which must be greater than zero). The create carries `expected_instrument_version` and, because attaching a study mutates the instrument's measurement-system record and advances the OCC guard, increments the instrument's version by one. A new study begins in `DRAFT`.

The study is filled by recording trial cells. A trial cell — a `GageRRTrial` — names its 1-based `operator_index` (from 1 to `operator_count`), `part_index` (from 1 to `part_count`), and `trial_index` (from 1 to `trial_count`), along with the `measured_value` for that operator-part-trial combination. The server records the owning `study_id`. Each combination must fall within the study's declared bounds and must not already be populated; an out-of-bounds index or a repeated cell is rejected with `ERR_DUPLICATE_TRIAL_CELL`.

The study advances through its own lifecycle, each transition incrementing the study's version. Opening it moves `DRAFT` to `COLLECTING`, permitted only when the owning instrument is `ACTIVE` (otherwise `ERR_INSTRUMENT_NOT_ACTIVE`) and the study is in `DRAFT` (otherwise `ERR_INVALID_STATE`). Analyzing it moves `COLLECTING` to `ANALYZED` and requires the trial matrix to be exactly complete — precisely the product of `operator_count`, `part_count`, and `trial_count` trial rows, one per cell, with no gaps and no duplicates (otherwise `ERR_INCOMPLETE_TRIAL_MATRIX`); analysis computes the study metrics described below. Accepting an `ANALYZED` study moves it to `ACCEPTED` (terminal) and requires that its `acceptability` not be `UNACCEPTABLE` (otherwise `ERR_GAGE_RR_UNACCEPTABLE`). Rejecting an `ANALYZED` study moves it back to `COLLECTING` for re-measurement, permitted only from `ANALYZED` (otherwise `ERR_INVALID_STATE`), and resets `ev_repeatability`, `av_reproducibility`, `grr`, `pct_grr`, and `acceptability` to null. A study in `DRAFT` or `COLLECTING` may be cancelled to `CANCELLED` (terminal); a cancel from any other state is rejected with `ERR_INVALID_STATE`.

The analysis computes the variation metrics from the full matrix of measured values in a pinned sequence, carrying full floating-point precision through the intermediate steps and rounding only at the very end. First, equipment variation (repeatability): for each operator-part pair, take the range as the maximum measured value minus the minimum across that pair's trials; average those ranges over all operator-part pairs to get the mean range; then `ev_repeatability` is the mean range multiplied by the AIAG constant for the trial count, where that constant is 4.56 for 2 trials, 3.05 for 3 trials, and 2.50 for 4 trials. Second, appraiser variation (reproducibility): for each operator, take that operator's grand mean over all of its part-and-trial readings; let the operator spread be the maximum such operator mean minus the minimum; then `av_reproducibility` is the square root of the larger of zero and the quantity formed by squaring the operator spread times the AIAG operator constant and subtracting from it the square of `ev_repeatability` divided by the product of `part_count` and `trial_count` — where the AIAG operator constant is 3.65 for 2 operators, 2.70 for 3 operators, and 2.30 for 4 operators. Third, the combined gage R&R `grr` is the square root of the sum of the squares of `ev_repeatability` and `av_reproducibility`.

Rounding is pinned to the final percentage only — never to the intermediate `ev_repeatability`, `av_reproducibility`, or `grr`, which are carried at full precision through the three steps above (and stored to 6 decimal places for display). The percentage `pct_grr` is one hundred times the quantity six times `grr` divided by `process_tolerance`, rounded half-up to 2 decimal places. The `acceptability` enum follows from that percentage: `ACCEPTABLE` when `pct_grr` is at most 10.00, `MARGINAL` when `pct_grr` is greater than 10.00 and at most 30.00, and `UNACCEPTABLE` when `pct_grr` is greater than 30.00.

### 3.8. The Logical Clock, Recall Sweep, and Drift Analytics

Time advances only by deliberate action. A `QualityEngineer` advances the clock by a `by_epochs` increment; the server adds that increment to `current_epoch` and then runs the recall sweep. The sweep visits every `ACTIVE` instrument whose `calibration_status` is `IN_TOLERANCE` and whose `next_due_epoch` is non-null and strictly less than the new `current_epoch`, and moves each such instrument's `calibration_status` to `OVERDUE`, incrementing the instrument's version. This is the same overdue derivation described in §3.4 — the due epoch drives the overdue flag, never the other way round — applied across the register after the clock moves. The clock may also be read by any role.

The drift trend is a read-only projection over an instrument's calibration history, offered under two methods chosen by the `method` query parameter, whose only accepted values are `LSQ` and `ENDPOINT` — any other supplied `method` is rejected with `ERR_INVALID_REQUEST` (HTTP 422). The input series is the instrument's finalized events — those whose status reflects a result of `PASS`, `CONDITIONAL`, or `FAIL`; `DRAFT`, `IN_PROGRESS`, and `CANCELLED` events are excluded — ordered by `scheduled_epoch` ascending with `created_at` ascending as the tie-break. Each event contributes a point whose horizontal coordinate is its `scheduled_epoch` and whose vertical coordinate is its `max_abs_deviation`. The default least-squares method (requested as LSQ or by omitting the parameter, and meaningful only when at least the minimum of 2 points are present) fits an ordinary least-squares slope over all points: the slope is the count of points times the sum of the products of paired coordinates, minus the product of the sum of horizontal coordinates and the sum of vertical coordinates, all divided by the count of points times the sum of squared horizontal coordinates minus the square of the sum of horizontal coordinates. The endpoint method (requested as ENDPOINT) instead takes the slope from only the first and last points: the last point's deviation minus the first point's deviation, divided by the last point's epoch minus the first point's epoch.

Under either method the slope is rounded to 6 decimal places round-half-up. When fewer than 2 points are present (insufficient for any fit), or when the slope denominator is zero (a degenerate series — for LSQ when the count times the sum of squared horizontal coordinates equals the square of their sum, or for ENDPOINT when the last and first points share the same epoch), both `slope` and `projected_breach_epoch` are reported as null while `point_count` and `method` are still returned. The projection then estimates when the instrument will breach tolerance: the `projected_breach_epoch` is the smallest integer epoch strictly greater than the last point's epoch at which the last point's deviation plus the slope times the elapsed epochs would exceed the instrument's tolerance half-band, where the half-band is the larger of `tolerance_plus` and `tolerance_minus`. When the slope is zero or negative there is no breach, and `projected_breach_epoch` is null. The drift read reports the `slope`, the `projected_breach_epoch`, the `point_count`, and the `method` used.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`; operations that modify, transition, or read an existing resource return `200 OK`. Request and response bodies are reconstructed from the workflow narratives in §3; the table below lists only the operational contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/advance` | Advance the logical clock by N epochs and run the recall sweep | QualityEngineer |
| GET | `/_clock` | Read the current logical clock | QualityEngineer, Technician, Metrologist |
| POST | `/calibration-standards` | Register a reference standard (NIST anchor when no parent) | Metrologist |
| GET | `/calibration-standards` | List standards; filter children by parent | Metrologist, Technician, QualityEngineer |
| GET | `/calibration-standards/{id}` | Get a standard with computed traceability fields | Metrologist, Technician, QualityEngineer |
| PUT | `/calibration-standards/{id}` | Update a standard's parent/certification | Metrologist |
| POST | `/calibration-vendors` | Register an external calibration vendor | Metrologist |
| GET | `/calibration-vendors` | List vendors | Metrologist, Technician, QualityEngineer |
| GET | `/calibration-vendors/{id}` | Get a vendor | Metrologist, Technician, QualityEngineer |
| PATCH | `/calibration-vendors/{id}` | Update vendor accreditation/status | Metrologist |
| POST | `/instruments` | Register an instrument/asset | QualityEngineer |
| GET | `/instruments` | List instruments; filter by lifecycle/calibration status | QualityEngineer, Technician, Metrologist |
| GET | `/instruments/{id}` | Get an instrument with computed due/recall fields | QualityEngineer, Technician, Metrologist |
| POST | `/instruments/{id}/release` | Release a QUARANTINED instrument back to ACTIVE | QualityEngineer |
| POST | `/instruments/{id}/retire` | Retire an instrument (terminal) | QualityEngineer |
| GET | `/instruments/{id}/drift-trend` | Computed drift trend over finalized calibration history | QualityEngineer, Technician, Metrologist |
| POST | `/instruments/{id}/calibration-events` | Open a DRAFT calibration event (OCC-guarded) | Technician |
| GET | `/instruments/{id}/calibration-events` | List an instrument's calibration events | QualityEngineer, Technician, Metrologist |
| GET | `/calibration-events/{id}` | Get a calibration event with computed result/tur/deviation | QualityEngineer, Technician, Metrologist |
| GET | `/calibration-events` | List calibration events filtered by standard or vendor | QualityEngineer, Technician, Metrologist |
| POST | `/calibration-events/{id}/start` | Move event DRAFT to IN_PROGRESS | Technician |
| POST | `/calibration-events/{id}/finalize` | Finalize event to PASS/CONDITIONAL/FAIL; cascade | Technician |
| POST | `/calibration-events/{id}/reopen` | Reopen a FAILED event after its impact is CANCELLED | Technician |
| POST | `/calibration-events/{id}/cancel` | Cancel a DRAFT event | Technician |
| POST | `/calibration-events/{id}/measurement-points` | Add a measurement point to a DRAFT/IN_PROGRESS event | Technician |
| GET | `/calibration-events/{id}/measurement-points` | List measurement points of an event | QualityEngineer, Technician, Metrologist |
| POST | `/calibration-events/{id}/certificates` | Issue a vendor certificate for the event | Metrologist |
| GET | `/calibration-events/{id}/certificates` | List certificates of an event | QualityEngineer, Technician, Metrologist |
| GET | `/certificates/{id}` | Get a certificate | QualityEngineer, Technician, Metrologist |
| GET | `/certificates` | List certificates filtered by vendor | QualityEngineer, Technician, Metrologist |
| POST | `/certificates/{id}/verify` | Verify an ISSUED certificate | Metrologist |
| POST | `/certificates/{id}/reject` | Reject an ISSUED certificate | Metrologist |
| POST | `/certificates/{id}/reissue` | Re-issue a REJECTED certificate | Metrologist |
| GET | `/instruments/{id}/impacts` | List an instrument's out-of-tolerance impacts | QualityEngineer, Technician, Metrologist |
| GET | `/impacts/{id}` | Get an impact with computed window and counts | QualityEngineer, Technician, Metrologist |
| GET | `/impacts` | List impacts filtered by triggering event | QualityEngineer, Technician, Metrologist |
| GET | `/impacts/{id}/exposure` | Computed recall exposure count (conservative/measured) | QualityEngineer, Metrologist |
| POST | `/impacts/{id}/investigate` | Move impact OPEN/ESCALATED to INVESTIGATING | QualityEngineer |
| POST | `/impacts/{id}/disposition` | Disposition impact; RECALL fans out a recall cascade | QualityEngineer |
| POST | `/impacts/{id}/escalate` | Escalate INVESTIGATING to ESCALATED (hold) | QualityEngineer |
| POST | `/impacts/{id}/cancel` | Cancel an OPEN impact | QualityEngineer |
| POST | `/impacts/{id}/affected-products` | Attach a product measured by the suspect instrument | QualityEngineer |
| GET | `/impacts/{id}/affected-products` | List affected products of an impact | QualityEngineer, Technician, Metrologist |
| POST | `/instruments/{id}/gage-rr-studies` | Create a DRAFT gage R&R study (OCC-guarded) | QualityEngineer |
| GET | `/instruments/{id}/gage-rr-studies` | List an instrument's gage R&R studies | QualityEngineer, Technician, Metrologist |
| GET | `/gage-rr-studies/{id}` | Get a gage R&R study with computed %GRR/acceptability | QualityEngineer, Technician, Metrologist |
| POST | `/gage-rr-studies/{id}/trials` | Record one operator-part-trial measurement cell | QualityEngineer, Technician |
| GET | `/gage-rr-studies/{id}/trials` | List a study's trial cells | QualityEngineer, Technician, Metrologist |
| POST | `/gage-rr-studies/{id}/open` | Open study DRAFT to COLLECTING | QualityEngineer |
| POST | `/gage-rr-studies/{id}/analyze` | Analyze a complete trial matrix; compute %GRR | QualityEngineer |
| POST | `/gage-rr-studies/{id}/accept` | Accept an ANALYZED study | QualityEngineer |
| POST | `/gage-rr-studies/{id}/reject` | Reject an ANALYZED study back to COLLECTING | QualityEngineer |
| POST | `/gage-rr-studies/{id}/cancel` | Cancel a DRAFT/COLLECTING study | QualityEngineer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_FK_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ASSET_TAG` | 409 Conflict |
| `ERR_DUPLICATE_CERTIFICATE_NUMBER` | 409 Conflict |
| `ERR_TRACEABILITY_CYCLE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INSTRUMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_INSTRUMENT_RETIRED` | 409 Conflict |
| `ERR_STANDARD_NOT_TRACEABLE` | 409 Conflict |
| `ERR_VENDOR_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NO_MEASUREMENT_POINTS` | 409 Conflict |
| `ERR_INCOMPLETE_TRIAL_MATRIX` | 409 Conflict |
| `ERR_NO_RECALLABLE_PRODUCT` | 409 Conflict |
| `ERR_OPEN_IMPACT_EXISTS` | 409 Conflict |
| `ERR_LATEST_CAL_NOT_PASSING` | 409 Conflict |
| `ERR_OPEN_CALIBRATION_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_TRIAL_CELL` | 409 Conflict |
| `ERR_GAGE_RR_UNACCEPTABLE` | 409 Conflict |
| `ERR_IMPACT_NOT_CANCELLED` | 409 Conflict |
| `ERR_RECALL_ALREADY_ISSUED` | 409 Conflict |
| `ERR_CERT_VENDOR_MISMATCH` | 409 Conflict |
| `ERR_EVENT_NOT_FINALIZED` | 409 Conflict |
| `ERR_STALE_INSTRUMENT_VERSION` | 412 Precondition Failed |

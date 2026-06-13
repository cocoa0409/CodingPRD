# Product Recall & Field Action API — Product Requirements Document

## 1. Introduction

When a manufactured product is found to carry a hazard, the manufacturer must act quickly and provably: identify exactly which lots and serial numbers are affected, decide how severe the danger is, notify every customer who owns an affected unit, recover or replace or refund those units, file the right paperwork with the right regulator on a deadline, and then prove to that regulator that the recovery effort actually worked. This API is the system of record for that entire field action. It coordinates the people who run a recall — the coordinators who scope and classify it, the quality officers who approve and close it, the field agents who handle returns and replacements, the finance clerks who settle refunds, and the platform operators who dispatch notifications — while keeping a defensible audit trail of who did what and when.

The domain is governed by two regulators with different rules of engagement: the FDA for medical and food products and the CPSC for consumer products. Both demand classified severity tiers (Class I, II, and III), time-boxed customer notification, and documented effectiveness. The system therefore treats classification, deadlines, segregation of duties, and effectiveness measurement as first-class, enforced constraints rather than advisory metadata. A recall progresses through a deliberate lifecycle, and at several points the system blocks the next step until the prerequisite evidence — an affected-lot list, an initial regulatory filing, a clean set of dispatched notifications, a passing effectiveness check, a final filing — is genuinely in place.

A second design pressure is consistency under concurrent edits. Recall scope, recovery counters, refund ledgers, and quarantine status all move together, and many operations cascade across several entities in a single request. Because multiple operators work the same recall, the system uses optimistic concurrency control on the two highest-contention write paths so that a stale client cannot silently clobber another operator's scope edit.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint. Entity-specific workflow logic lives in Section 3.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. Authentication is gated solely on the `X-User-Role` header: if the `X-User-Role` header is missing or does not name one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`; a missing `X-User-ID` is not by itself an authentication failure (its presence is never separately verified). If the role is recognized but is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly five roles, spelled precisely as follows: `RecallCoordinator`, `QualityOfficer`, `FieldServiceAgent`, `FinanceClerk`, and `PlatformAdmin`. A `RecallCoordinator` opens recalls, declares affected lots, classifies and reclassifies, begins monitoring, manages quarantine holds, drafts reports, and records effectiveness checks. A `QualityOfficer` is the independent approver who announces classified recalls, terminates recalls, and signs and submits regulatory reports. A `FieldServiceAgent` registers units and customers and drives disposition logistics. A `FinanceClerk` accrues and settles refunds. A `PlatformAdmin` is the operational backbone: it dispatches and acknowledges notifications, acknowledges regulatory reports, controls the test clock, and holds superset create access used for environment setup.

All five roles use an **opaque identity model**. When `X-User-Role` is `RecallCoordinator`, `QualityOfficer`, `FieldServiceAgent`, `FinanceClerk`, or `PlatformAdmin`, the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity; the server never compares it to any entity's `id` for ownership purposes. The server does, however, record specific operator identifiers where the workflow demands accountability — for example it writes the classifying coordinator's `X-User-ID` into `classified_by_user_id`, the approving officer's into `approved_by_user_id`, and the submitting officer's into `signed_by_user_id`. These recorded identifiers drive the four-eyes segregation check (described in Section 3) but never act as resource-ownership keys.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, may not be smaller than 1, and may not exceed 100. The `offset` parameter is the number of items to skip from the start of the result set; it defaults to 0.

Unless an endpoint explicitly states otherwise, all list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order. Every list response includes the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Resource Identity

Every primary resource — `Product`, `Lot`, `Unit`, `Customer`, `Recall`, `QuarantineHold`, `Notification`, `Disposition`, `RegulatoryReport`, and `EffectivenessCheck` — carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` field is an integer that begins at 1 on creation and increments by one on every mutation, including mutations that only touch computed/derived fields.

There is one exception. The `AffectedLot` membership record is an immutable junction row created once and never modified; it therefore carries only `id` and `created_at`. It has no `updated_at` and no `version` field at all.

### 2.5. Derived Fields and Cascading Reconciliation

Many fields in this system are **computed**, not supplied by the client, and the server is responsible for keeping them consistent the moment any input that feeds them changes. A `Lot`'s `manufactured_units` is the count of serial numbers in its declared range. A `Lot`'s `quarantine_status` reflects whether any active hold currently targets it. A `Unit`'s `affected` flag reflects whether the unit falls inside an active recall's scope. A `Recall` carries a family of derived counters — `affected_unit_count`, `recovered_unit_count`, `effectiveness_pct`, and `total_refund_cents` — plus its derived `classification`, `notification_deadline_hours`, and `active_recall_id` linkage on the owning `Product`. Each of these is recomputed synchronously, inside the request that triggers the change, before the response is returned; the system never defers reconciliation to a background pass.

Cascades frequently touch more than one entity in a single request. When the server recomputes a child or parent during such a cascade, that reconciliation independently mutates the affected resource — refreshing its `updated_at` and incrementing its `version` — exactly as a direct edit would. Section 3 specifies, per workflow, which secondary entities each operation reconciles; this subsection establishes only that all such reconciliation is immediate and version-bumping.

### 2.6. Nested and Referenced Resource Resolution

This API uses a flat topology: every entity is a sibling root collection (`/products`, `/lots`, `/recalls`, and so on), and resources are joined by explicit foreign-key fields carried in request bodies rather than by nested URL paths. Whenever a request names a resource — whether as a path identifier such as the `{id}` of a recall, or as a foreign-key field inside the body such as `product_id`, `lot_id`, `unit_id`, `customer_id`, `recall_id`, or `report_kind`'s owning recall — the server validates those references in left-to-right order: the path identifier first, then body references in the order they are read. The first reference that fails to resolve to an existing resource causes immediate rejection with `ERR_NOT_FOUND`, before any business rule is evaluated.

### 2.7. Validation Ordering

When several checks could apply to one request, they are evaluated in a fixed priority order so that the same bad request always yields the same error. Authentication comes first: a missing or unrecognized role yields `ERR_UNAUTHENTICATED`. Authorization comes next: a recognized role lacking permission for the endpoint yields `ERR_FORBIDDEN_ROLE`. Existence comes third: any unresolved path identifier or foreign key yields `ERR_NOT_FOUND`. Body well-formedness comes fourth: a missing required field, an invalid enum value, or an out-of-range integer (for example `serial_end` below `serial_start`, or `unit_list_price_cents` below 1) yields `ERR_INVALID_REQUEST`. On the two OCC-guarded write paths, the stale-version check comes fifth and yields `ERR_STALE_VERSION`. The generic state check comes sixth: a transition attempted from a state that does not permit it yields `ERR_INVALID_STATE`. Only after all of these pass does the system evaluate domain-specific business rules, which are themselves ordered safety-and-compliance before fiscal — the per-endpoint ordering details are given alongside each workflow in Section 3.

### 2.8. Optimistic Concurrency Control

Two write paths are guarded by optimistic concurrency control against the parent `Recall`. Both require the caller to submit `expected_recall_version`, carrying the `version` of the target recall as the client last observed it. The server compares that value to the recall's current `version`; on any mismatch the write is rejected with `ERR_STALE_VERSION` at HTTP 412.

The first guarded path is declaring an affected lot. Because each affected-lot declaration bumps `Recall.version` and recomputes `affected_unit_count`, a client working from a stale view of the recall could double-count or contradict a prior scope edit; submitting `expected_recall_version` and having it match the recall's current `version` is mandatory, and a mismatch is rejected with `ERR_STALE_VERSION` so the client cannot extend a scope it has not seen. The second guarded path is opening a disposition. A recall's recovery counters, effectiveness percentage, and `active_recall_id` linkage are recomputed by sibling disposition and lifecycle writes, each bumping `Recall.version`; opening a disposition therefore requires `expected_recall_version` to equal the recall's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` so the client cannot open a disposition against a recall that has since moved past the disposition-open window. These two paths are the only ones that take a version field; no other endpoint accepts or requires `expected_recall_version`.

### 2.9. Monetary and Percentage Precision

All money in this system is held and transacted in integer **cents**; there are no fractional cents. Where a calculation produces a non-integer cent figure — notably the Class I goodwill premium — the result is rounded to the nearest whole cent using the round-half-up convention (a value exactly halfway between two cents rounds up). Effectiveness percentages (`effectiveness_pct`, `measured_pct`, and the `target_pct` comparison basis) are expressed as numbers carrying two decimal places, also using round-half-up. Counts (`affected_unit_count`, `recovered_unit_count`, `manufactured_units`, `attempt_count`, `lifted_count`, `unit_count_snapshot`) and deadline hours (`notification_deadline_hours`) are exact integers with no rounding.

### 2.10. Time and the Test Clock

Regulatory filing deadlines are evaluated against the server's notion of "now." To make deadline evaluation deterministic under test, an administrative test-driving capability lets a `PlatformAdmin` pin the server's current UTC clock to a supplied instant via the `to_iso8601` field; every subsequent deadline evaluation reads that pinned value as the current time. This capability has no domain side effects beyond setting the clock and returns no resource body.

## 3. Business Logic & Workflows

### 3.1. Establishing the Product Catalogue: Products, Lots, and Units

Before any recall can exist, the affected goods must be modeled. A `Product` is registered with a manufacturer `sku`, a display `name`, a governing `regulator` that is one of `FDA` or `CPSC`, and a `unit_list_price_cents` that must be at least 1. The `sku` is globally unique across all products; a collision is rejected with `ERR_DUPLICATE_KEY`. A product also carries a computed `active_recall_id`, which holds the `id` of the one recall currently in a non-terminal state for that product, or is null when there is none — at most one such recall may be active at a time, and the field is set to null at creation.

A `Lot` represents a manufactured batch of a product and is declared with a `product_id`, a `lot_code`, and an inclusive contiguous serial range given by `serial_start` and `serial_end`. Both bounds must be at least 1, and `serial_end` must be greater than or equal to `serial_start`. From those bounds the system computes `manufactured_units` as `serial_end` minus `serial_start` plus one — the total count of serial numbers in the range. A new lot's `lot_code` must be unique within its `product_id`, and a duplicate is rejected with `ERR_DUPLICATE_KEY`. Furthermore, a new lot's serial range must not collide with any existing lot of the same product. Collision uses closed-interval semantics: the new range collides with an existing range whenever the new `serial_start` is less than or equal to the existing `serial_end` **and** the new `serial_end` is greater than or equal to the existing `serial_start`. Touching endpoints collide — if an existing lot ends at serial 100 and a new lot starts at serial 100, the two ranges collide because serial 100 cannot belong to two lots — and such an attempt is rejected with `ERR_LOT_RANGE_OVERLAP`. Each lot also exposes a computed `quarantine_status` of either `RELEASED` or `HELD`; it is `RELEASED` by default and at creation, becoming `HELD` only while an active quarantine hold targets it.

A `Unit` is an individual sold serial, registered with a `lot_id`, a `serial_number`, a `customer_id` naming its current owner, and a `sale_price_cents` recording what the customer actually paid, which must be at least 0. The `serial_number` must fall within its lot's inclusive `serial_start` to `serial_end` range; a serial outside that range is rejected with `ERR_SERIAL_OUT_OF_RANGE`. The `serial_number` must also be unique within its `lot_id`, with a duplicate rejected with `ERR_DUPLICATE_KEY`. Each unit carries a computed `affected` boolean, false by default, which the system recomputes at registration and which becomes true only when the unit's lot belongs to an active recall's affected-lot set and its serial falls within that recall's serial filter (the exact recompute rule is given in Section 3.4).

A `Customer` is the owner-of-record contacted during a recall, created with a `name`, a `contact_channel` of `EMAIL`, `SMS`, or `MAIL`, a matching `contact_address`, and a `reachable` flag indicating whether that address is currently deliverable. The `reachable` flag defaults to true when omitted. A customer's contact details and reachability may later be updated.

### 3.2. Opening and Scoping a Recall

A `RecallCoordinator` (or a `PlatformAdmin` performing setup) opens a recall against a product, supplying the `product_id`, a free-text `reason`, an operator-assessed `hazard_severity` of `SERIOUS`, `TEMPORARY`, or `MINOR`, and an optional `injury_reported` flag that defaults to false. The recall's scope of serials may be narrowed with an optional `serial_filter_start` and `serial_filter_end`; either may be omitted, and an omitted lower bound means there is no lower bound while an omitted upper bound means there is no upper bound. A freshly opened recall begins in `DRAFT` status.

Opening a recall is constrained so that two live recalls cannot fight over the same serials of one product. A new recall's affected serial window must not overlap the window of any existing non-terminal recall on the same `product_id` — non-terminal meaning any recall whose status is neither `TERMINATED` nor `EFFECTIVE`. These windows use unbounded, extended-real semantics: a null `serial_filter_start` is treated as negative infinity and a null `serial_filter_end` as positive infinity. Two windows overlap when the larger of their two start bounds is less than or equal to the smaller of their two end bounds under that extended arithmetic. A consequence worth noting is that, unlike finite closed lot ranges, an unbounded recall window collides with any other window on the same product. A violation is rejected with `ERR_RECALL_WINDOW_OVERLAP`.

Scope is given substance by declaring affected lots. The relationship between a recall and the lots it covers is many-to-many, expressed through `AffectedLot` membership rows. Declaring a lot affected is a coordinator action that names the `lot_id` and, because it is one of the two optimistic-concurrency-guarded writes, must also carry `expected_recall_version` matching the recall's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` at HTTP 412 (see Section 2.8). On a successful declaration the system creates the `AffectedLot`, captures `unit_count_snapshot` equal to the lot's `manufactured_units` at that moment, recomputes the `affected` flag on the units in that lot, recomputes the recall's `affected_unit_count` and `effectiveness_pct`, and increments the recall's `version` by one.

### 3.3. Classification, Reclassification, and the Notification Window

Once a recall has at least one affected lot, a `RecallCoordinator` classifies it, advancing it from `DRAFT` to `CLASSIFIED`. Classification is refused if the recall has zero affected lots, rejected with `ERR_NO_AFFECTED_LOTS`. It is also refused if a serial filter is present but inverted — that is, if both `serial_filter_start` and `serial_filter_end` are present and the start exceeds the end — rejected with `ERR_INVALID_SERIAL_FILTER`. Between these two, the affected-lots prerequisite is evaluated as the conflict-class check and the inverted-filter check as the malformed-input check.

Classification derives the recall's regulatory `classification`, which is one of `CLASS_I`, `CLASS_II`, or `CLASS_III`. The tier is decided from `hazard_severity` together with `injury_reported`: when the hazard is `SERIOUS` and an injury has been reported, the recall is `CLASS_I`; when the hazard is `SERIOUS` but no injury has been reported, it is `CLASS_II`; when the hazard is `TEMPORARY`, regardless of injury, it is `CLASS_II`; and when the hazard is `MINOR`, it is `CLASS_III`. The single differentiator between `CLASS_I` and `CLASS_II` at `SERIOUS` severity is the `injury_reported` flag — identical severity, different class, driven solely by whether an injury was reported.

Immediately after the tier is set, the system derives the regulator-mandated customer-notification window, stored as `notification_deadline_hours`, from three interacting inputs: the new `classification`, the recalled product's `regulator`, and `injury_reported`. The CPSC fast-tracks injury cases regardless of tier: when an injury has been reported and the regulator is `CPSC`, the window is 24 hours. Otherwise, a `CLASS_I` recall has a 24-hour window. A `CLASS_II` recall has a 72-hour window when the regulator is `FDA` and a 120-hour window when the regulator is `CPSC`. A `CLASS_III` recall has a 240-hour window (that is, ten days). Classification also records `classified_by_user_id` as the acting coordinator's `X-User-ID`, recomputes the `affected` flag on every unit in the recall's affected lots, recomputes `affected_unit_count` and `effectiveness_pct`, and sets the owning product's `active_recall_id` to this recall's id.

Scope sometimes needs revision after a first classification. A `RecallCoordinator` may reclassify a `CLASSIFIED` recall back to `DRAFT`, optionally supplying revised `hazard_severity`, `injury_reported`, `serial_filter_start`, or `serial_filter_end` values, which are applied as field edits. Reclassification clears the derived `classification`, `notification_deadline_hours`, and `classified_by_user_id`, and recomputes the `affected` flag on every unit in the recall's affected lots. This forms a deliberate cyclic loop — `DRAFT → CLASSIFIED → DRAFT` — letting a coordinator revise severity or scope and re-classify. Reclassification is forbidden, however, once the recall's paperwork has begun: if any `RegulatoryReport` for the recall is already `SUBMITTED` or `ACKNOWLEDGED`, the reclassify is rejected with `ERR_REPORT_ALREADY_FILED`.

### 3.4. The Affected-Flag Recompute

The `affected` flag on a unit is the linchpin connecting recall scope to dispositions and effectiveness, and it is recomputed whenever the recall is classified or reclassified, whenever an affected lot is added, and whenever a unit is created. For each unit whose `lot_id` is among the recall's affected lots, the system evaluates two conditions: the unit's lot is in the affected-lot set, and the unit's `serial_number` falls within the recall's serial filter — meaning the serial is greater than or equal to `serial_filter_start` when that bound is present (any serial qualifies on the low side when it is null) and less than or equal to `serial_filter_end` when that bound is present (any serial qualifies on the high side when it is null). A unit's `affected` flag is set to true only when its lot is in the affected set, its serial is within the filter, and the recall is not in `DRAFT` status; in every other case, including any unit outside the affected lots, the flag is false.

### 3.5. Regulatory Reporting

Regulatory filings are the recall's external evidence trail, and they gate the lifecycle at two points. A report is drafted — by either a `RecallCoordinator` or a `QualityOfficer` — against a `recall_id` with a `report_kind` of `INITIAL`, `FOLLOWUP`, or `FINAL`. An `INITIAL` filing is the early 24-hour or 15-day notice, a `FOLLOWUP` is a periodic status update, and a `FINAL` is the termination filing. A new report begins in `DRAFTED` status and carries a computed `agency` (snapshotting the recalled product's `regulator` at filing time), a computed `filed_within_deadline` flag, a `status`, and a `signed_by_user_id`. At draft creation these three computed fields — `agency`, `filed_within_deadline`, and `signed_by_user_id` — are all null; they are populated only at submission (filing time) as described below.

A `QualityOfficer` signs and submits a drafted report, advancing it from `DRAFTED` to `SUBMITTED`. Submission is refused while the owning recall is still `DRAFT`, because a classification must exist before anything is filed; that attempt is rejected with `ERR_RECALL_NOT_CLASSIFIED`. On submission the system records `signed_by_user_id` as the acting officer's `X-User-ID` and snapshots `agency` from the recalled product's `regulator`. When the report's `report_kind` is `INITIAL`, the system also evaluates `filed_within_deadline`: it is true when the initial report is submitted within the regulator deadline window appropriate to the recall's classification — the same `notification_deadline_hours` window derived at classification — measured against the server's current clock. The window is measured from the recall's `created_at` timestamp: `filed_within_deadline` is true when the server's current clock at submission is at most `notification_deadline_hours` hours after the recall's `created_at`, with the boundary inclusive (a submission landing exactly on the deadline counts as within). For a non-`INITIAL` report `filed_within_deadline` is left null. A `PlatformAdmin` later acknowledges a submitted report, advancing it from `SUBMITTED` to `ACKNOWLEDGED`, which is the report's terminal state.

### 3.6. Announcing the Recall: Segregation, Quarantine Cascade, and Notification Fan-Out

Announcement is the moment a recall goes public, and it is reserved for a `QualityOfficer` acting as an independent approver — it moves the recall from `CLASSIFIED` to `ANNOUNCED`. Two preconditions guard it, evaluated as compliance gates before the cascade runs. First, four-eyes segregation of duties: the announcing officer's `X-User-ID` must differ from the recall's `classified_by_user_id`; the same user may not both classify and approve the same recall, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. Second, the paperwork prerequisite: at least one `INITIAL` regulatory report for this recall must already be `SUBMITTED` or `ACKNOWLEDGED`, and an announcement without it is rejected with `ERR_INITIAL_REPORT_REQUIRED`.

When both gates pass, the system records `approved_by_user_id` as the announcing officer's `X-User-ID` and then runs two cascades. The quarantine cascade creates one new `ACTIVE` `QuarantineHold` for each affected lot that does not already have one; each newly active hold in turn drives its target lot's `quarantine_status` to `HELD`. The framing matters: the lot status change is caused by the hold's `ACTIVE` state, not directly by the recall. The notification fan-out creates one `QUEUED` `Notification` for each distinct customer who owns at least one affected unit under this recall — one notification per distinct customer, not per unit.

### 3.7. Quarantine Holds and the Lift/Reimpose Cycle

A `QuarantineHold` ties a recall to a lot it has frozen. While most holds are born during the announce cascade, a hold records its `recall_id`, its `lot_id`, an operator `reason`, a `status` of either `ACTIVE` or `LIFTED`, and a `lifted_count` that starts at 0 and counts how many times the hold has gone from `ACTIVE` to `LIFTED`. A lot is `HELD` whenever any active hold targets it and `RELEASED` only when no active hold remains.

A `RecallCoordinator` may lift an `ACTIVE` hold, moving it to `LIFTED`, but only when the owning recall has progressed far enough — its status must be `MONITORING`, `EFFECTIVE`, or `TERMINATED`; an attempt while the recall is in any earlier state is rejected with `ERR_HOLD_LOCKED_BY_RECALL`. Lifting increments `lifted_count` by one and recomputes the target lot's `quarantine_status`: the lot stays `HELD` if any other active hold still targets it, and otherwise becomes `RELEASED`. A `LIFTED` hold may be re-imposed back to `ACTIVE` by a `RecallCoordinator`, forming a cyclic `ACTIVE → LIFTED → ACTIVE` loop, but only while the owning recall is neither `TERMINATED` nor `EFFECTIVE`; otherwise it too is rejected with `ERR_HOLD_LOCKED_BY_RECALL`. Re-imposition recomputes the target lot's `quarantine_status` to `HELD`.

### 3.8. The Notification Cascade and Its Send Branches

Each `Notification` addresses one customer about one recall, recording the `recall_id`, the `customer_id`, a computed `channel` that snapshots the customer's `contact_channel` at send time, a `status`, and an `attempt_count` that starts at 0 and increments on each send attempt. Notifications are born `QUEUED` during the announce fan-out.

A `PlatformAdmin` attempts delivery, and a single send trigger forks on the addressee's reachability. When the customer's `reachable` flag is true, the notification moves from `QUEUED` to `SENT`; the attempt increments `attempt_count` by one and snapshots `channel` from the customer's `contact_channel`. When the customer's `reachable` flag is false, the same send trigger instead moves the notification from `QUEUED` to `FAILED`, incrementing `attempt_count` by one. A failed notification may be retried once the customer becomes reachable: a send on a `FAILED` notification moves it to `SENT` when `reachable` is true, again incrementing `attempt_count` and snapshotting `channel`. The reachability guard is applied asymmetrically by source state. A send on a `QUEUED` notification never raises the guard: it always produces a branch — `SENT` when `reachable` is true, otherwise the `FAILED` branch that records the failed attempt (`attempt_count` incremented). The `ERR_CUSTOMER_UNREACHABLE` guard is raised only on a send of a `FAILED` notification while the customer is unreachable; in that case the notification is left unchanged and `attempt_count` is not incremented. In short, `FAILED → SENT` and `QUEUED → SENT` require `reachable` to be true, the `QUEUED → FAILED` branch fires when `reachable` is false, and a `FAILED` retry against an unreachable customer is the only path rejected with `ERR_CUSTOMER_UNREACHABLE`. A `SENT` notification can be marked `ACKNOWLEDGED` by a `PlatformAdmin`, which is terminal and counts toward notification-complete gating.

The recall cannot leave the announced phase until its notifications are settled. A `RecallCoordinator` begins monitoring, moving the recall from `ANNOUNCED` to `MONITORING`, but only when every notification for the recall is in `SENT`, `ACKNOWLEDGED`, or `FAILED` — that is, none remain `QUEUED`. An attempt with at least one `QUEUED` notification still outstanding is rejected with `ERR_NOTIFICATIONS_PENDING`. Effectiveness checks are typically recorded once the recall is `MONITORING`, though the system does not itself enforce that lifecycle state on the check-recording endpoint (see Section 3.11).

### 3.9. Dispositions: Parallel Logistics and Financial Tracks

A `Disposition` resolves a single affected unit, and it is the most intricate object in the system because it carries two independent state dimensions on one row: a `logistics_status` and a `financial_status` that evolve in parallel. A `FieldServiceAgent` opens a disposition by naming the `recall_id`, the `unit_id`, the `disposition_type` (one of `RETURN`, `REPLACE`, or `REFUND`), and an optional `refund_basis` of `SALE_PRICE` or `LIST_PRICE` that defaults to `SALE_PRICE`. Because opening a disposition is the second optimistic-concurrency-guarded write, the request must also carry `expected_recall_version` matching the recall's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` at HTTP 412 (see Section 2.8). A newly opened disposition starts with `logistics_status` of `PENDING` and `financial_status` of `NOT_OWED`, and opening it increments the recall's `version` by one. The disposition also carries a computed `refund_amount_cents`, which stays 0 until a refund is settled.

Opening a disposition is hedged by several guards, evaluated in this fixed order after the OCC stale-version check: the recall-open gate first, then the unit-affected gate, then the duplicate gate. Dispositions may be opened and advanced only while the owning recall is `ANNOUNCED` or `MONITORING`; outside that window the operation is rejected with `ERR_RECALL_NOT_OPEN_FOR_DISPOSITION`. The unit must actually be affected: a disposition may be opened only for a unit whose `affected` flag is true under the recall, and otherwise is rejected with `ERR_UNIT_NOT_AFFECTED`. There may be at most one open disposition (one whose `logistics_status` is `PENDING`) per recall-and-unit pair, and a duplicate is rejected with `ERR_DUPLICATE_DISPOSITION`.

On the logistics track, a `FieldServiceAgent` records a return receipt, moving `logistics_status` from `PENDING` to `RETURNED`; this is permitted only when the `disposition_type` is `RETURN` or `REFUND` (otherwise `ERR_DISPOSITION_TYPE_MISMATCH`) and the owning recall is `ANNOUNCED` or `MONITORING` (otherwise `ERR_RECALL_NOT_OPEN_FOR_DISPOSITION`), and it recomputes the recall's `recovered_unit_count` and `effectiveness_pct`. An agent ships a replacement, moving `logistics_status` from `PENDING` to `REPLACED`; this requires the `disposition_type` to be exactly `REPLACE` (otherwise `ERR_DISPOSITION_TYPE_MISMATCH`) and the recall to be `ANNOUNCED` or `MONITORING` (otherwise `ERR_RECALL_NOT_OPEN_FOR_DISPOSITION`), and likewise recomputes `recovered_unit_count` and `effectiveness_pct`. An agent may also cancel a disposition, moving `logistics_status` to `CANCELLED`; cancel is permitted from a `logistics_status` of either `PENDING` or `RETURNED`. The already-refunded refusal is evaluated first: cancellation is refused if the disposition has already been refunded (`financial_status` of `REFUNDED`), rejected with `ERR_DISPOSITION_ALREADY_REFUNDED`. If that guard passes, the cancel proceeds when `logistics_status` is `PENDING` or `RETURNED`; from any other `logistics_status` it is rejected with `ERR_INVALID_STATE`. When a disposition is cancelled while its `financial_status` is `OWED`, that financial status is set to `VOID`; cancellation in any case recomputes `recovered_unit_count` and `effectiveness_pct`.

On the financial track, a `FinanceClerk` accrues a refund liability, moving `financial_status` from `NOT_OWED` to `OWED`; this is permitted only when the `disposition_type` is `REFUND` (otherwise `ERR_DISPOSITION_TYPE_MISMATCH`) and the unit's return has already been received — that is, the `logistics_status` is `RETURNED` (otherwise `ERR_RETURN_NOT_RECEIVED`). A `FinanceClerk` then settles the refund, moving `financial_status` from `OWED` to `REFUNDED`; settlement likewise requires `logistics_status` to be `RETURNED` (otherwise `ERR_RETURN_NOT_RECEIVED`). Settlement fixes `refund_amount_cents` via the refund-amount rule below and recomputes the recall's `total_refund_cents`.

### 3.10. Refund Amount and the Recall Ledger

The settled refund amount is fixed exactly at the moment a refund moves from `OWED` to `REFUNDED`, and it depends on two choices: which price basis to refund and whether the recall is Class I. The base in cents is the unit's `sale_price_cents` when the disposition's `refund_basis` is `SALE_PRICE` — what the customer actually paid — and the recalled product's `unit_list_price_cents` when the basis is `LIST_PRICE`. The two bases diverge whenever the unit sold at a discount or premium relative to list. On top of the base, the system applies a goodwill premium for the most serious recalls: when the owning recall's `classification` is `CLASS_I`, the `refund_amount_cents` is the base multiplied by 1.10 (a 10 percent goodwill premium that regulators encourage for serious hazards), rounded to the nearest whole cent using round-half-up; for any other classification, the `refund_amount_cents` is the base with no premium.

The recall's `total_refund_cents` is the running sum of settled refunds. The rounding order is deliberately pinned: each disposition's `refund_amount_cents` is rounded to whole cents at its own settlement — round-half-up applied per line item, including the Class I premium — and only then are the settled amounts summed, with no further rounding applied to the total. In other words the system rounds per line and then sums; it never sums raw products and rounds once at the end. Concretely, `total_refund_cents` is the exact integer sum of `refund_amount_cents` across every disposition of the recall whose `financial_status` is `REFUNDED`.

### 3.11. Effectiveness Measurement and Closing the Recall

Effectiveness is the recovery rate the regulator cares about, and the system keeps it live on the recall. The recompute is intentionally ordered to break what looks like a circular dependency, and it runs whenever a disposition reaches `RETURNED`, `REPLACED`, or `CANCELLED`, and whenever the affected-flag recompute runs. Step one counts the affected universe: `affected_unit_count` is the number of units whose `affected` flag is true. Step two counts recoveries: `recovered_unit_count` is the number of dispositions of this recall whose `logistics_status` is either `RETURNED` or `REPLACED` and whose dispositioned unit is affected — cancelled dispositions never count as recovered. Step three computes the rate: when `affected_unit_count` is zero, `effectiveness_pct` is 0; otherwise `effectiveness_pct` is `recovered_unit_count` divided by `affected_unit_count`, multiplied by 100, rounded half-up to two decimal places.

An `EffectivenessCheck` freezes a point-in-time judgment of that rate against a per-class target. Recorded by a `RecallCoordinator` or a `QualityOfficer` against a `recall_id`, the check derives a `target_pct` from the recall's classification — 90 for `CLASS_I`, 60 for `CLASS_II`, and 30 for `CLASS_III` — and snapshots `measured_pct` as the recall's current `effectiveness_pct` (two decimal places) at the moment of recording. Recording is not gated on the recall's lifecycle state — the endpoint accepts a check against a recall in any status, and there is no state-based rejection error for it — and when the recall has not yet been classified (its `classification` is null) the `target_pct` defaults to the `CLASS_III` value of 30. Its `outcome` is `PASS` when `measured_pct` is greater than or equal to `target_pct`, using an inclusive boundary, and `FAIL` otherwise.

Closing a recall is a `QualityOfficer` action with two outcomes that share one trigger but diverge on their preconditions. The successful close advances the recall from `MONITORING` to `EFFECTIVE`: it requires that the latest `EffectivenessCheck` for the recall has `outcome` of `PASS` (otherwise `ERR_EFFECTIVENESS_NOT_MET`) and that a `FINAL` regulatory report for the recall is `SUBMITTED` or `ACKNOWLEDGED` (otherwise `ERR_FINAL_REPORT_REQUIRED`). The administrative close advances the recall from `MONITORING` to `TERMINATED`: it likewise requires a `FINAL` report that is `SUBMITTED` or `ACKNOWLEDGED` (otherwise `ERR_FINAL_REPORT_REQUIRED`), and it is selected by passing `force_terminate` as true in the request, which permits closing without meeting the effectiveness target and records an unmet-effectiveness close. When `force_terminate` is false (or omitted) and the latest effectiveness check fails, the close is rejected with `ERR_EFFECTIVENESS_NOT_MET` rather than terminating. Either close — to `EFFECTIVE` or to `TERMINATED` — lifts every `ACTIVE` quarantine hold on the recall's affected lots, recomputes each released lot's `quarantine_status` to `RELEASED`, and clears the owning product's `active_recall_id`. `TERMINATED` is the recall's only terminal state.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that drive a state transition on an existing resource or otherwise modify one return a `200 OK` status code. The clock-control endpoint returns `200 OK` and no resource body.

The table below lists only the method, path, a short description, and the authorized roles. The request and response shapes, side effects, and preconditions for each operation are specified in the Section 3 narratives, which must be consulted to reconstruct the full contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/products` | Create a Product | RecallCoordinator, PlatformAdmin |
| GET | `/products/{id}` | Get a Product | RecallCoordinator, QualityOfficer, FieldServiceAgent, FinanceClerk, PlatformAdmin |
| GET | `/products` | List Products (filter by sku or regulator) | RecallCoordinator, QualityOfficer, FieldServiceAgent, FinanceClerk, PlatformAdmin |
| POST | `/lots` | Create a Lot for a product | RecallCoordinator, PlatformAdmin |
| GET | `/lots/{id}` | Get a Lot | RecallCoordinator, QualityOfficer, FieldServiceAgent, FinanceClerk, PlatformAdmin |
| GET | `/lots` | List Lots (filter by product_id) | RecallCoordinator, QualityOfficer, FieldServiceAgent, FinanceClerk, PlatformAdmin |
| POST | `/units` | Register a Unit sold to a customer | RecallCoordinator, FieldServiceAgent, PlatformAdmin |
| GET | `/units/{id}` | Get a Unit | RecallCoordinator, QualityOfficer, FieldServiceAgent, FinanceClerk, PlatformAdmin |
| GET | `/units` | List Units (filter by lot_id, customer_id, affected) | RecallCoordinator, QualityOfficer, FieldServiceAgent, FinanceClerk, PlatformAdmin |
| POST | `/customers` | Create a Customer | RecallCoordinator, FieldServiceAgent, PlatformAdmin |
| GET | `/customers/{id}` | Get a Customer | RecallCoordinator, QualityOfficer, FieldServiceAgent, FinanceClerk, PlatformAdmin |
| PATCH | `/customers/{id}` | Update a Customer's contact details / reachability | RecallCoordinator, FieldServiceAgent, PlatformAdmin |
| POST | `/recalls` | Open a Recall in DRAFT | RecallCoordinator, PlatformAdmin |
| GET | `/recalls/{id}` | Get a Recall (computed counters/effectiveness included) | RecallCoordinator, QualityOfficer, FieldServiceAgent, FinanceClerk, PlatformAdmin |
| GET | `/recalls` | List Recalls (filter by product_id or status) | RecallCoordinator, QualityOfficer, FieldServiceAgent, FinanceClerk, PlatformAdmin |
| POST | `/recalls/{id}/affected-lots` | Declare a Lot affected by the recall (OCC-guarded) | RecallCoordinator, PlatformAdmin |
| GET | `/affected-lots/{id}` | Get an AffectedLot membership record | RecallCoordinator, QualityOfficer, FieldServiceAgent, FinanceClerk, PlatformAdmin |
| GET | `/affected-lots` | List AffectedLots (filter by recall_id or lot_id) | RecallCoordinator, QualityOfficer, FieldServiceAgent, FinanceClerk, PlatformAdmin |
| POST | `/recalls/{id}/classify` | Classify the recall (DRAFT → CLASSIFIED) | RecallCoordinator |
| POST | `/recalls/{id}/reclassify` | Send a CLASSIFIED recall back to DRAFT for revision | RecallCoordinator |
| POST | `/recalls/{id}/announce` | Approve & announce (CLASSIFIED → ANNOUNCED) | QualityOfficer |
| POST | `/recalls/{id}/begin-monitoring` | Move ANNOUNCED → MONITORING | RecallCoordinator |
| POST | `/recalls/{id}/terminate` | Close recall (→ EFFECTIVE or → TERMINATED) | QualityOfficer |
| GET | `/recalls/{id}/effectiveness` | Computed read: current effectiveness summary (returns the full Recall resource, whose computed counters and `effectiveness_pct` are the summary) | RecallCoordinator, QualityOfficer, FinanceClerk, PlatformAdmin |
| GET | `/quarantine-holds/{id}` | Get a QuarantineHold | RecallCoordinator, QualityOfficer, FieldServiceAgent, FinanceClerk, PlatformAdmin |
| GET | `/quarantine-holds` | List QuarantineHolds (filter by recall_id, lot_id, status) | RecallCoordinator, QualityOfficer, FieldServiceAgent, FinanceClerk, PlatformAdmin |
| POST | `/quarantine-holds/{id}/lift` | Lift an ACTIVE hold (ACTIVE → LIFTED) | RecallCoordinator |
| POST | `/quarantine-holds/{id}/reimpose` | Re-impose a LIFTED hold (LIFTED → ACTIVE) | RecallCoordinator |
| GET | `/notifications/{id}` | Get a Notification | RecallCoordinator, QualityOfficer, PlatformAdmin |
| GET | `/notifications` | List Notifications (filter by recall_id, customer_id, status) | RecallCoordinator, QualityOfficer, PlatformAdmin |
| POST | `/notifications/{id}/send` | Attempt to send a notification | PlatformAdmin |
| POST | `/notifications/{id}/acknowledge` | Mark a SENT notification ACKNOWLEDGED | PlatformAdmin |
| POST | `/dispositions` | Open a Disposition for an affected unit (OCC-guarded) | FieldServiceAgent |
| GET | `/dispositions/{id}` | Get a Disposition | RecallCoordinator, QualityOfficer, FieldServiceAgent, FinanceClerk, PlatformAdmin |
| GET | `/dispositions` | List Dispositions (filter by recall_id, unit_id, logistics_status, financial_status) | RecallCoordinator, QualityOfficer, FieldServiceAgent, FinanceClerk, PlatformAdmin |
| POST | `/dispositions/{id}/receive-return` | Record return receipt (logistics PENDING → RETURNED) | FieldServiceAgent |
| POST | `/dispositions/{id}/ship-replacement` | Ship replacement unit (logistics PENDING → REPLACED) | FieldServiceAgent |
| POST | `/dispositions/{id}/cancel` | Cancel a disposition (logistics PENDING or RETURNED → CANCELLED) | FieldServiceAgent |
| POST | `/dispositions/{id}/accrue-refund` | Accrue a refund liability (financial NOT_OWED → OWED) | FinanceClerk |
| POST | `/dispositions/{id}/settle-refund` | Settle the refund (financial OWED → REFUNDED) | FinanceClerk |
| POST | `/regulatory-reports` | Draft a regulatory report for a recall | RecallCoordinator, QualityOfficer |
| GET | `/regulatory-reports/{id}` | Get a RegulatoryReport | RecallCoordinator, QualityOfficer, PlatformAdmin |
| GET | `/regulatory-reports` | List RegulatoryReports (filter by recall_id, report_kind, status) | RecallCoordinator, QualityOfficer, PlatformAdmin |
| POST | `/regulatory-reports/{id}/submit` | Sign & submit a report (DRAFTED → SUBMITTED) | QualityOfficer |
| POST | `/regulatory-reports/{id}/acknowledge` | Mark a report ACKNOWLEDGED (SUBMITTED → ACKNOWLEDGED) | PlatformAdmin |
| POST | `/effectiveness-checks` | Record an effectiveness check | RecallCoordinator, QualityOfficer |
| GET | `/effectiveness-checks/{id}` | Get an EffectivenessCheck | RecallCoordinator, QualityOfficer, FinanceClerk, PlatformAdmin |
| GET | `/effectiveness-checks` | List EffectivenessChecks (filter by recall_id, outcome) | RecallCoordinator, QualityOfficer, FinanceClerk, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Test-driving: pin the server's current UTC clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_KEY` | 409 |
| `ERR_SERIAL_OUT_OF_RANGE` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_NO_AFFECTED_LOTS` | 409 |
| `ERR_INVALID_SERIAL_FILTER` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_INITIAL_REPORT_REQUIRED` | 409 |
| `ERR_FINAL_REPORT_REQUIRED` | 409 |
| `ERR_NOTIFICATIONS_PENDING` | 409 |
| `ERR_EFFECTIVENESS_NOT_MET` | 409 |
| `ERR_HOLD_LOCKED_BY_RECALL` | 409 |
| `ERR_CUSTOMER_UNREACHABLE` | 409 |
| `ERR_UNIT_NOT_AFFECTED` | 409 |
| `ERR_DUPLICATE_DISPOSITION` | 409 |
| `ERR_DISPOSITION_TYPE_MISMATCH` | 409 |
| `ERR_RETURN_NOT_RECEIVED` | 409 |
| `ERR_RECALL_NOT_OPEN_FOR_DISPOSITION` | 409 |
| `ERR_DISPOSITION_ALREADY_REFUNDED` | 409 |
| `ERR_RECALL_NOT_CLASSIFIED` | 409 |
| `ERR_REPORT_ALREADY_FILED` | 409 |
| `ERR_LOT_RANGE_OVERLAP` | 409 |
| `ERR_RECALL_WINDOW_OVERLAP` | 409 |

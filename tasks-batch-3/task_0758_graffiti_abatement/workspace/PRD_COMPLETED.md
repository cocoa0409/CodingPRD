# Graffiti Abatement API — Product Requirements Document

## 1. Introduction

Municipal graffiti and nuisance abatement is a coordination problem before it is a cleanup problem. A single defaced wall generates a 311 call, a geolocation, a severity judgment, a crew, a batch of paint, a property-owner conversation, and — when the property is private — a bill that the city is entitled to recover. This document specifies the Graffiti Abatement API, the system of record that stitches those moving parts into one auditable workflow: report intake and triage, priority scoring, crew dispatch and material reservation, field execution with before/after photo evidence, cost assessment, property-owner notices, and cost recovery up to and including liens.

The platform serves several distinct constituencies whose actions must remain strictly separated yet tightly interlocked. Residents and 311 clerks file reports; coordinators triage, dispatch, and negotiate with owners; crew leads execute work in the field; inventory managers keep paint and solvent on the shelf; property owners respond to notices and settle balances; and program administrators hold override and waiver authority. Because a completed abatement simultaneously touches inventory, a crew's availability, a site's repeat-offender posture, and a financial ledger, every operation in this API is expected to reconcile all of its downstream consequences atomically, inside the request that triggered it.

A final design constraint shapes the entire specification: time is logical, not wall-clock. Ninety-day hotspot windows, notice cure deadlines, and every recorded timestamp are all measured against a server-controlled logical clock so that the program's temporal behavior is fully reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts — authentication, response shape, pagination, precision, consistency, and concurrency — that govern every endpoint uniformly.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly seven roles: `Resident`, `IntakeClerk`, `AbatementCoordinator`, `CrewLead`, `InventoryManager`, `PropertyOwnerUser`, and `ProgramAdmin`.

Two of these roles are **entity-backed**, meaning their `X-User-ID` is not an anonymous operator label but the identity of a specific persisted resource:

- When `X-User-Role` is `CrewLead`, `X-User-ID` is the `id` of the acting `Crew`. Ownership checks on any work order compare the work order's `crew_id` to `X-User-ID`: a crew lead may start, complete, or attach photos to a work order only when that work order's `crew_id` equals their `X-User-ID`.
- When `X-User-Role` is `PropertyOwnerUser`, `X-User-ID` is the `id` of the acting `PropertyOwner`. Ownership checks on any notice or cost recovery resolve to the site behind the resource and compare that site's `property_owner_id` to `X-User-ID`: an owner may consent to a notice, dispute a notice, or pay a cost recovery only when the underlying site's `property_owner_id` equals their `X-User-ID`.

When an entity-backed role acts on a resource it does not own, the request is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).

The remaining five roles — `Resident`, `IntakeClerk`, `AbatementCoordinator`, `InventoryManager`, and `ProgramAdmin` — are **opaque**: their `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record such an identifier where a transition writes it — for example as `logged_by` on a `RemovalLog` entry produced by a recall — but it never compares an opaque `X-User-ID` to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. A `limit` below 1 is clamped to 1 and above 100 to 100, an `offset` below 0 is clamped to 0, and a `limit` or `offset` that is present but not parseable as an integer is rejected with `ERR_INVALID_REQUEST`. Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order, with ties on `created_at` broken by order of creation (insertion order).

Every list response reports `limit`, `offset`, `total_count`, and `has_more` in the `meta` object. Beyond `limit` and `offset`, individual list endpoints accept domain filters that narrow the collection before pagination is applied: sites may be filtered by `property_owner_id` and by `status`; reports by `site_id`, `status`, and `severity`; work orders by `report_id`, `crew_id`, and `status`; notices by `site_id`, `cost_recovery_id`, and `status`; and cost recoveries by `site_id`, `work_order_id`, and `status`. These filters are the system's reverse-reachability mechanism — the way a caller walks from a parent entity to the children that reference it.

### 2.4. Common Resource Properties and Identifiers

Most resources carry a common set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation, and `version` is an integer that begins at 1 on creation and increments by one on every mutation (an operation that touches an entity more than once within a single request still advances that entity's `version` by exactly one). These four fields are present on `PropertyOwner`, `Site`, `Report`, `Crew`, `WorkOrder`, `MaterialReservation`, `Material`, `CostRecovery`, and `Notice`.

Two resources are append-only audit records and therefore carry **only** `id` and `created_at` — they have neither `updated_at` nor `version`: the `Photo` and the `RemovalLog`. Once written, they are never modified.

### 2.5. The Logical Clock and Temporal Semantics

All time-dependent behavior in the system reads from a single logical clock rather than the host's wall clock. On startup the clock reads exactly `2026-03-01T00:00:00Z`, and until it is explicitly moved it never falls back to real time. A program administrator may advance or reset the clock by supplying a target instant in the `to_iso8601` field; this is an administrative test-driving capability with no domain side effects beyond moving the clock that stamps timestamps, opens hotspot windows, and closes cure deadlines. Because the clock is deterministic, the 90-day hotspot window, a notice's cure deadline, and every `created_at`, `captured_at`, `sent_at`, and `response_at` value are all reproducible.

### 2.6. Monetary Precision and Line-Item Rounding

All monetary amounts are stored and returned as integer counts of whole cents. Wherever a cost is computed, rounding uses the **round half up** convention. A structural rule governs the order of operations for any abatement cost: **each line item is rounded to whole cents first, and only the already-rounded lines are summed** — the system never sums raw products and rounds once at the end. The labor line is rounded on its own, each material reservation's line is rounded on its own before the material lines are added together, and the administrative fee is computed from the already-rounded labor-plus-material subtotal and then rounded. The complete costing procedure is specified in §3.3 and §3.5.

### 2.7. Cascading State Reconciliation and Derived-Field Consistency

The system's consistency model is immediate: when an operation changes one entity, every downstream consequence is applied atomically within the same request, and no derived field is ever left stale for a reader to discover later. A crew lead completing a work order, for instance, does not merely close that work order — in the same transaction it consumes the reserved materials, frees the crew, remediates the report, assesses the cost recovery, credits the site ledger, recomputes the site's confirmed hotspot index, and appends a removal-log entry. Each entity touched by such a cascade has its own `updated_at` refreshed and its own `version` incremented as an independent mutation.

Derived fields on the `Site` — `status`, `report_count_90d`, `open_report_count`, `hotspot_severity_index_rolling`, `hotspot_severity_index_confirmed`, `outstanding_recovery_cents`, and `lien_count` — are reconciled on write by whatever operation changes their inputs, never lazily. Likewise the `Material` derived fields `quantity_reserved` and `status`, and the `CostRecovery` derived amounts, are recomputed at the moment their inputs move.

### 2.8. Nested Resource Retrieval and Existence Validation

Several resources are addressed beneath a parent in the URL — a work order's photos, its removal logs, and its material reservations, and the reservations recorded against a material. For any request whose path or body references other resources, existence is validated left to right: the system checks each referenced identifier in order — `site_id`, then `report_id`, then `crew_id`, then `material_id`, then `work_order_id`, then `cost_recovery_id`, then `notice_id`, then `property_owner_id` — and rejects the request at the first identifier that does not resolve, returning the matching not-found error: `ERR_SITE_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_MATERIAL_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_COST_RECOVERY_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, or `ERR_PROPERTY_OWNER_NOT_FOUND`, each carrying HTTP 404.

### 2.9. Optimistic Concurrency Control for Notice Issuance

Issuing a property-owner notice is the one operation guarded by optimistic concurrency, because issuance both supersedes the site's prior outstanding notice and mutates the site itself. A notice-issuance request must carry `expected_site_version`, and its value must equal the target site's current `version`. If the site's `version` has advanced since the client last read it — for example because a prior notice issuance already moved the site past the client's view — the request is rejected with `ERR_STALE_SITE_VERSION` (HTTP 412), so that a client cannot supersede a notice landscape it has not observed. No other endpoint accepts or requires a version field; only notice issuance performs this check.

### 2.10. Validation Ordering

When several checks could reject one request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication comes first: a missing or unknown role yields `ERR_UNAUTHENTICATED`. Authorization is second: a role not permitted on the endpoint yields `ERR_UNAUTHORIZED`. Third is request well-formedness — required fields present, types and enums valid, and `scheduled_end` strictly after `scheduled_start` — a failure of which yields `ERR_INVALID_REQUEST` (HTTP 400). Fourth is existence of every referenced resource, per §2.8. Fifth is entity-backed ownership, yielding `ERR_OWNERSHIP_MISMATCH`. Sixth is the generic state guard: if the target resource is not in a state from which the requested transition is defined, the request is rejected with `ERR_INVALID_STATE` (HTTP 409). Only after all six of these pass does the system evaluate the operation-specific business rules described in §3 — crew availability, offensive certification, scheduling conflicts, photo prerequisites, material sufficiency, cure-window timing, the site-version check, and the rest. This ordering matters: an unauthenticated caller sending a malformed body still sees `ERR_UNAUTHENTICATED`, and a state violation is reported before any deeper business rule is consulted.

## 3. Business Logic & Workflows

### 3.1. Sites, Ownership, and Repeat-Hotspot Posture

Every abatement begins with a **Site** — a physical location described by an `address`, a geolocation given as `latitude` and `longitude` of the site centroid, and an `ownership_type` that is either `PUBLIC` (city-owned) or `PRIVATE` (owner-billable). Ownership drives billing, so it is constrained at creation: a `PRIVATE` site must name the responsible owner through `property_owner_id`, and a `PUBLIC` site must not carry one. Creating a `PRIVATE` site with no `property_owner_id`, or a `PUBLIC` site with one, is rejected with `ERR_PRIVATE_SITE_REQUIRES_OWNER` (HTTP 422). A property owner is registered independently with a `name`, a `mailing_address` used for physical notices, and a `contact_email` for electronic notices.

A new site starts with `status` of `NORMAL` and all of its computed counters at zero: `report_count_90d`, `open_report_count`, `hotspot_severity_index_rolling`, `hotspot_severity_index_confirmed`, `outstanding_recovery_cents`, and `lien_count`, along with a null `active_notice_id`. As reports accumulate, the site's posture reflects how much recent activity it carries. The `report_count_90d` is the number of the site's reports whose `created_at` falls within the trailing 90-day window ending at the current clock instant, and `open_report_count` is the number of the site's reports whose `status` is neither `REMEDIATED` nor `CLOSED`.

The `status` posture is recomputed on every report creation and on every change to a report's status, and it moves as follows. From `NORMAL`, once the count of reports in the 90-day window reaches exactly 2, the site becomes `MONITORED`. From `MONITORED`, once that count reaches 3 or more, the site becomes `HOTSPOT`. Posture also relaxes as activity ages out or reports close: a `HOTSPOT` site whose in-window count falls back to exactly 2 returns to `MONITORED`, and a `MONITORED` site whose in-window count falls to 1 or fewer returns to `NORMAL`.

Two rolling severity indices summarize how serious that activity is. Each report contributes a severity weight — `LOW` weighs 1, `MEDIUM` weighs 2, `HIGH` weighs 4, and `SEVERE` weighs 8. The `hotspot_severity_index_rolling` is the sum of those weights over **every** report of the site whose `created_at` lies in the 90-day window, regardless of report status, giving a live picture of current pressure. The `hotspot_severity_index_confirmed` is the sum of the same weights but only over the in-window reports whose `status` is `REMEDIATED`, giving an effectiveness picture of work actually completed. Both indices are integers and both are recomputed whenever a report is created or a report's status changes.

Sites can be fetched individually or listed; the list view supports the `property_owner_id` and `status` filters described in §2.3, letting a caller reach every site belonging to one owner or every site currently in a given posture.

### 3.2. Report Intake and Triage Scoring

A **Report** is the 311 record of a specific nuisance. Residents and intake clerks file reports against a site through `site_id`, recording the intake channel in `reported_via` (one of `PHONE_311`, `WEB`, or `MOBILE_APP`), the affected `surface_type` (one of `WALL`, `FENCE`, `SIGN`, `SIDEWALK`, or `VEHICLE`), a clerk-assessed `severity` (`LOW`, `MEDIUM`, `HIGH`, or `SEVERE`), and a free-text `description`. Three inputs are optional: `is_offensive` marks hateful or offensive content and defaults to false; `latitude` and `longitude` pin the precise incident and default to null; and `reporter_contact` records an optional call-back contact and defaults to null. A newly filed report enters `SUBMITTED` status with a null `priority_score`.

Filing a report is itself a posture event. On creation, the site's `report_count_90d` and `open_report_count` are incremented and the site's `status` posture together with both hotspot severity indices are recomputed, exactly as described in §3.1. The report list view supports the `site_id`, `status`, and `severity` filters so a coordinator can survey a site's history or sweep the queue by urgency.

**Triage** is the intake clerk's (or coordinator's) act of scoring a submitted report and advancing it `SUBMITTED → TRIAGED`; it is permitted only when the report is currently `SUBMITTED`, and it computes and stores the `priority_score`. The score is a weighted combination read against the site's posture *at the moment of triage*. Start from a severity base — 10 for `LOW`, 25 for `MEDIUM`, 50 for `HIGH`, and 80 for `SEVERE`. Multiply that base by a surface-visibility factor determined by `surface_type`: a `SIGN` factor of 1.5, a `WALL` factor of 1.2, a `VEHICLE` factor of 1.1, a `FENCE` factor of 1.0, and a `SIDEWALK` factor of 0.8. To that product add a flat offensive bonus of 40 when the report's `is_offensive` is true (and nothing when it is false), and add a further flat public-property adjustment of 5 when the site's `ownership_type` is `PUBLIC` (and nothing when it is `PRIVATE`). Finally, multiply the whole sum by a posture multiplier read from the site's current `status`: 1.5 when the site is `HOTSPOT`, 1.2 when it is `MONITORED`, and 1.0 when it is `NORMAL`. Round the result half up to two decimal places and store it as `priority_score`. Because the posture multiplier is read at triage time, the same report scores higher on a site that has since escalated to `HOTSPOT` than it would have on a quiet site.

### 3.3. Crew Dispatch, Material Reservation, and Provisional Cost

A **Crew** is registered with a display `name`, a `crew_type` of `CITY` or `CONTRACTOR`, and an `is_offensive_certified` flag (default false) marking whether the crew may abate offensive content. A crew's `status` is `AVAILABLE` when idle and `DISPATCHED` while it is executing an in-progress work order; it starts `AVAILABLE`.

Dispatch is the coordinator's act of committing a triaged report to a crew, and it is the system's most consequential single request. The coordinator supplies the `report_id` being abated, the `crew_id` to send, a `scheduled_start` and `scheduled_end` bounding the abatement window (with `scheduled_end` required to be strictly after `scheduled_start`), the removal `method` (`PAINT_OVER`, `PRESSURE_WASH`, or `CHEMICAL`), an `estimated_labor_hours` figure, and an optional `material_lines` list. Each entry in `material_lines` names a `material_id` and the quantity to reserve from it, supplied in a `quantity` field that must be a number strictly greater than 0. Dispatch is defined only from a report in `TRIAGED` status; a successful dispatch advances the report `TRIAGED → DISPATCHED` and creates a **WorkOrder** in `SCHEDULED` status.

Before the work order is created, several safety and feasibility gates apply, all specific to dispatch. The chosen crew must be `AVAILABLE`; a crew already `DISPATCHED` on another job causes `ERR_CREW_UNAVAILABLE` (HTTP 409). If the report's `is_offensive` is true, the crew's `is_offensive_certified` must also be true, or the dispatch is rejected with `ERR_CREW_NOT_CERTIFIED` (HTTP 422). The crew must be free during the window: if the crew has any other non-terminal work order whose half-open interval from its `scheduled_start` up to (but not including) its `scheduled_end` overlaps the new window, the request is rejected with `ERR_CREW_SCHEDULE_CONFLICT` (HTTP 409). A private-property spacing rule also applies: for a `PRIVATE` site, no other non-terminal work order on the same site may fall within a 24-hour buffer of the new window — concretely, a conflict exists when the new window's start is earlier than the other window's end plus 24 hours **and** the other window's start is earlier than the new window's end plus 24 hours — and a violation yields `ERR_SITE_ABATEMENT_BUFFER_CONFLICT` (HTTP 409). Finally, materials must be in stock: each requested line quantity is checked cumulatively across the request against that material's `quantity_available`, and any shortfall raises `ERR_INSUFFICIENT_MATERIAL` (HTTP 409).

When those gates pass, dispatch performs its full cascade atomically. It creates one **MaterialReservation** per `material_lines` entry, each in `RESERVED` status recording its `work_order_id`, its `material_id`, and the `quantity_reserved` taken from the line; for each, the reserved quantity is moved out of the material's `quantity_available` and into its `quantity_reserved`, leaving the material's total holdings unchanged. It also opens a **CostRecovery** in `PENDING` status, referencing the site via `site_id` and the work order via `work_order_id`, with its provisional amounts filled in from the estimated-cost variant of the abatement-cost calculation.

That calculation, in its **provisional** variant, uses the work order's `estimated_labor_hours` and the reservations' `quantity_reserved` quantities. The labor line is the labor hours multiplied by a labor rate of 6500 cents per hour, rounded half up to whole cents, and stored as `labor_cost_cents`. The material line is computed per reservation — each reservation's quantity multiplied by its material's `unit_cost_cents`, rounded half up on its own — and those per-reservation amounts are then summed into `material_cost_cents`. The subtotal is `labor_cost_cents` plus `material_cost_cents`; the administrative fee is 15 percent of that rounded subtotal, itself rounded half up, and stored as `admin_fee_cents`. The provisional total, stored as `estimated_cost_cents`, is the sum of the rounded labor line, the summed material line, and the rounded admin fee. The recoverable amount, `recoverable_cents`, equals that total when the site's `ownership_type` is `PRIVATE` and is 0 for a `PUBLIC` site. At the `PENDING` stage the recovery's `final_cost_cents` remains null.

### 3.4. Field Execution: Photos, Start, Completion, Recall, and Cancel

Fieldwork is documented photographically. A crew lead uploads a **Photo** to their work order with a `phase` of `BEFORE` or `AFTER` and a storage `url`; the server stamps `captured_at` from the logical clock. A `BEFORE` photo is the evidence prerequisite for starting, and an `AFTER` photo the prerequisite for completing. Photos, removal logs, and material reservations for a work order can each be listed through their nested collections.

**Starting** a work order advances the report `DISPATCHED → IN_PROGRESS` and the work order `SCHEDULED → IN_PROGRESS`. It may be invoked only by the crew lead who owns the crew (the work order's `crew_id` must equal the acting `X-User-ID`), only while the report is `DISPATCHED`, and only if at least one `BEFORE` photo already exists for the work order — a missing before-photo is rejected with `ERR_BEFORE_PHOTO_REQUIRED` (HTTP 422). Starting also drives the crew `AVAILABLE → DISPATCHED` and appends a `RemovalLog` entry whose `action` is `STARTED`, whose `logged_by` records the acting user, and whose optional `note` carries any note from the transition.

**Completing** a work order is the remediation arm of the in-progress fork. The crew lead supplies `actual_labor_hours`; completion is defined only while the report is `IN_PROGRESS`, requires that at least one `AFTER` photo exist (otherwise `ERR_AFTER_PHOTO_REQUIRED`, HTTP 422), and requires crew ownership. On success the system advances the work order `IN_PROGRESS → COMPLETED`, sets its `actual_labor_hours`, and runs the full completion cascade atomically: for every `RESERVED` reservation it sets `quantity_consumed` equal to that reservation's `quantity_reserved`, moves the reservation to `CONSUMED`, and credits the consumed amount back out of the material's `quantity_reserved` so the material permanently leaves inventory; it frees the crew `DISPATCHED → AVAILABLE`; it advances the report `IN_PROGRESS → REMEDIATED` when the site's `ownership_type` is `PRIVATE`, but on a `PUBLIC` site — where there is nothing to recover — the report is instead advanced directly `IN_PROGRESS → CLOSED` in this same step, so it never passes through `REMEDIATED` and therefore never contributes to `hotspot_severity_index_confirmed`; it advances the cost recovery `PENDING → ASSESSED` (for a `PUBLIC` site this assessed recovery carries `recoverable_cents` of 0); it recomputes the site's `hotspot_severity_index_confirmed` and `open_report_count`; and it appends a `RemovalLog` entry with `action` `COMPLETED`.

At the `PENDING → ASSESSED` step the cost recovery is finalized from the **final** variant of the abatement-cost calculation, which is identical in structure to the provisional variant but reads the work order's `actual_labor_hours` in place of the estimate and each reservation's `quantity_consumed` in place of its reserved quantity. This recomputes `labor_cost_cents`, `material_cost_cents`, and `admin_fee_cents` on the recovery, sets `final_cost_cents` to the final total, and recomputes `recoverable_cents` (the final total for a `PRIVATE` site, 0 for a `PUBLIC` site). Assessment then credits the site's `outstanding_recovery_cents` by the recovery's `recoverable_cents`.

The in-progress fork's other arm is **recall**, the coordinator's abort-and-revise path, which diverges sharply from completion. Recall is defined only while the work order is `IN_PROGRESS`; it accepts an optional `reason`, advances the work order `IN_PROGRESS → RECALLED`, and returns the report `IN_PROGRESS → TRIAGED` so it can be re-dispatched — the non-linear revision cycle that carries a report from `TRIAGED` through `DISPATCHED` and `IN_PROGRESS` back to `TRIAGED`. Recall **releases** rather than consumes materials: every `RESERVED` reservation moves to `RELEASED`, crediting its quantity back to the material's `quantity_available` and debiting the material's `quantity_reserved`. It frees the crew `DISPATCHED → AVAILABLE`, voids the cost recovery `PENDING → VOID`, and appends a `RemovalLog` entry with `action` `RECALLED`.

**Cancelling** handles the pre-execution case: a coordinator may cancel a work order still in `SCHEDULED` (with an optional `reason`), which advances the work order `SCHEDULED → CANCELLED`, returns the report `DISPATCHED → TRIAGED`, releases every `RESERVED` reservation back to inventory exactly as recall does, and voids the cost recovery `PENDING → VOID`. Because a `PENDING` recovery was never counted in the site's outstanding balance, both cancel and recall void it with no change to `outstanding_recovery_cents`.

### 3.5. Cost Recovery, Payment, Waiver, and the Site Ledger

A **CostRecovery** carries the money for one abatement from provisional estimate through final assessment to settlement, moving among `PENDING`, `ASSESSED`, `DISPUTED`, `WAIVED`, `LIEN_PENDING`, `PAID`, and `VOID`. Its amounts — `estimated_cost_cents`, `final_cost_cents`, `labor_cost_cents`, `material_cost_cents`, `admin_fee_cents`, and `recoverable_cents` — are computed as described in §3.3 and §3.4; `WAIVED`, `PAID`, and `VOID` are terminal. Cost recoveries can be fetched or listed, filtered by `site_id`, `work_order_id`, and `status`.

Once a recovery is `ASSESSED`, it awaits settlement. A property owner (or a coordinator acting on their behalf) may **pay** an assessed recovery: payment is defined only from `ASSESSED`, requires that the acting owner own the site's property owner, advances the recovery `ASSESSED → PAID`, and debits the site's `outstanding_recovery_cents` by the recovery's `recoverable_cents`. A program administrator may instead **waive** an assessed recovery: waiver is likewise defined only from `ASSESSED`, accepts an optional `reason`, advances the recovery `ASSESSED → WAIVED`, and also debits the site's `outstanding_recovery_cents` by the recovery's `recoverable_cents`. In both cases, if the recovery's linked report is currently `REMEDIATED`, the settlement cascades that report `REMEDIATED → CLOSED`.

That closing cascade is the general rule for report finalization: a `PRIVATE` site's report advances `REMEDIATED → CLOSED` once its cost recovery reaches a terminal recovery state — `PAID` or `WAIVED`; a `PUBLIC` site's report, having nothing to recover, is instead closed directly at completion (`IN_PROGRESS → CLOSED`, per §3.4) rather than first resting in `REMEDIATED`.

The site's `outstanding_recovery_cents` is, at all times, the sum of `recoverable_cents` over the site's cost recoveries whose `status` is `ASSESSED`, `DISPUTED`, or `LIEN_PENDING`. Assessment adds a recovery to that outstanding pool; payment and waiver remove it; a dispute or a lien-escalation keeps it in the pool. The site also tracks `lien_count`, the number of its recoveries that have reached `LIEN_PENDING`.

### 3.6. Property-Owner Notices and Escalation to Lien

A **Notice** is the formal communication served to a private property owner. It references the served site through `site_id`, carries a `notice_type` of `ABATEMENT_NOTICE` or `COST_RECOVERY_NOTICE`, and a `cure_days` count. When the type is `COST_RECOVERY_NOTICE`, the notice must reference the recovery in question through `cost_recovery_id`; for an `ABATEMENT_NOTICE`, `cost_recovery_id` is null. Issuance is a coordinator action against a site and is guarded by the optimistic-concurrency rule of §2.9: the request must include `expected_site_version` matching the site's current `version`, or it is rejected with `ERR_STALE_SITE_VERSION` (HTTP 412). Additionally, a `COST_RECOVERY_NOTICE` may be issued only while its linked cost recovery is `ASSESSED`; issuing against a recovery in any other state is rejected with `ERR_RECOVERY_NOT_ASSESSED` (HTTP 409).

On issuance, the new notice starts in `SENT` status; the server stamps `sent_at` from the clock and computes `cure_deadline` as `sent_at` plus `cure_days` days, leaving `response_at` null until the owner responds. Issuance supersedes whatever came before: any prior `SENT` notice for the same site is driven `SENT → WITHDRAWN`, the site's `active_notice_id` is repointed to the new notice, and the site's `version` is incremented by one — which is precisely why a stale `expected_site_version` must be rejected. Notices can be listed with the `site_id`, `cost_recovery_id`, and `status` filters.

From `SENT`, the owner may respond. **Consent** advances the notice `SENT → CONSENTED`, requires owner ownership, sets `response_at`, and clears the site's `active_notice_id` if it still pointed at this notice. **Dispute** advances the notice `SENT → DISPUTED`, also requires ownership, sets `response_at`, and — when the notice carries a `cost_recovery_id` whose recovery is `ASSESSED` — cascades that recovery `ASSESSED → DISPUTED` (a status change that keeps the recovery in the outstanding pool, so the site ledger is unchanged). A disputed notice is not terminal: the owner may later consent on it, advancing `DISPUTED → CONSENTED`, which sets `response_at`, clears the site's `active_notice_id` if it pointed here, and — when the linked recovery is `DISPUTED` — resolves it back `DISPUTED → ASSESSED`, again with no ledger movement.

If the owner never responds, the coordinator may **expire** the notice once the cure period has elapsed. Expiry is defined only from `SENT` and only when the current clock instant is at or after the notice's `cure_deadline`; an attempt before that instant is rejected with `ERR_CURE_WINDOW_NOT_ELAPSED` (HTTP 409). Expiry advances the notice `SENT → EXPIRED`, clears the site's `active_notice_id` if it pointed here, and — when the notice carries a `cost_recovery_id` whose recovery is `ASSESSED` — escalates that recovery `ASSESSED → LIEN_PENDING`. That escalation is itself a two-step cascade: reaching `LIEN_PENDING` keeps the recovery in the outstanding pool (no ledger change) and increments the site's `lien_count` by one. A prior `SENT` notice may also be withdrawn without any owner action, purely as the side effect of a superseding issuance described above.

### 3.7. Paint and Material Inventory

An inventory manager stocks the shelf with **Material** lines. Each material has a `name`, a `category` of `PAINT`, `SOLVENT`, or `ABRASIVE`, an optional `color` label (default null), a `unit` of `LITERS` or `GALLONS`, a `unit_cost_cents` used in material line-item costing, an initial `quantity_available`, and an optional `reorder_threshold` (default 0). At creation the material's `quantity_reserved` is initialized to 0 and its `status` is derived from stock on hand.

The conserved invariant of the inventory is that `quantity_available` plus `quantity_reserved` is unchanged by any reserve-or-release pair: dispatch moves stock from available to reserved, release moves it back, and completion consumes reserved stock out of the system entirely. The material's `status` is derived from its available quantity on every such change: it is `DEPLETED` when `quantity_available` is at or below 0; otherwise it is `LOW` when `quantity_available` is at or below the `reorder_threshold`; otherwise it is `AVAILABLE`. A material can be fetched directly, and the reservations drawn against it can be listed through its nested reservation collection, letting an inventory manager trace exactly which work orders are holding stock.

## 4. Endpoint Definitions

Endpoints that create a new, distinct resource return `201 Created`; state transitions and other modifications to existing resources return `200 OK`. The administrative clock endpoint returns `200 OK`. In the table below, "All roles" denotes every one of the seven roles, which is the read access granted to all `GET` endpoints.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | ProgramAdmin |
| POST | `/abatement/property-owners` | Register a property owner | AbatementCoordinator, ProgramAdmin |
| GET | `/abatement/property-owners/{id}` | Fetch a property owner | All roles |
| POST | `/abatement/sites` | Create a site with geolocation and ownership | IntakeClerk, AbatementCoordinator, ProgramAdmin |
| GET | `/abatement/sites/{id}` | Fetch a site with posture and ledgers | All roles |
| GET | `/abatement/sites` | List sites | All roles |
| POST | `/abatement/reports` | Intake a 311 report | Resident, IntakeClerk |
| GET | `/abatement/reports/{id}` | Fetch a report | All roles |
| GET | `/abatement/reports` | List reports | All roles |
| POST | `/abatement/reports/{id}/triage` | Triage a report and compute its priority score | IntakeClerk, AbatementCoordinator |
| POST | `/abatement/crews` | Register an abatement crew | AbatementCoordinator, ProgramAdmin |
| GET | `/abatement/crews/{id}` | Fetch a crew | All roles |
| POST | `/abatement/work-orders` | Dispatch a crew to a triaged report | AbatementCoordinator |
| GET | `/abatement/work-orders/{id}` | Fetch a work order | All roles |
| GET | `/abatement/work-orders` | List work orders | All roles |
| POST | `/abatement/work-orders/{id}/start` | Start abatement | CrewLead |
| POST | `/abatement/work-orders/{id}/complete` | Complete abatement and assess cost | CrewLead |
| POST | `/abatement/work-orders/{id}/cancel` | Cancel a scheduled work order | AbatementCoordinator |
| POST | `/abatement/work-orders/{id}/recall` | Recall an in-progress work order | AbatementCoordinator |
| POST | `/abatement/work-orders/{id}/photos` | Upload a before/after photo | CrewLead |
| GET | `/abatement/work-orders/{id}/photos` | List a work order's photos | All roles |
| GET | `/abatement/work-orders/{id}/removal-logs` | List a work order's removal log | All roles |
| GET | `/abatement/work-orders/{id}/material-reservations` | List a work order's material reservations | All roles |
| POST | `/abatement/materials` | Add a paint/material stock line | InventoryManager, ProgramAdmin |
| GET | `/abatement/materials/{id}` | Fetch a material stock line | All roles |
| GET | `/abatement/materials/{id}/material-reservations` | List reservations against a material | All roles |
| POST | `/abatement/sites/{id}/notices` | Issue a property-owner notice | AbatementCoordinator |
| GET | `/abatement/notices/{id}` | Fetch a notice | All roles |
| GET | `/abatement/notices` | List notices | All roles |
| POST | `/abatement/notices/{id}/consent` | Owner consents to a notice | PropertyOwnerUser |
| POST | `/abatement/notices/{id}/dispute` | Owner disputes a notice | PropertyOwnerUser |
| POST | `/abatement/notices/{id}/expire` | Expire a notice past its cure deadline | AbatementCoordinator |
| GET | `/abatement/cost-recoveries/{id}` | Fetch a cost recovery | All roles |
| GET | `/abatement/cost-recoveries` | List cost recoveries | All roles |
| POST | `/abatement/cost-recoveries/{id}/pay` | Owner pays an assessed cost recovery | PropertyOwnerUser, AbatementCoordinator |
| POST | `/abatement/cost-recoveries/{id}/waive` | Admin waives an assessed cost recovery | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_OWNERSHIP_MISMATCH` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_PROPERTY_OWNER_NOT_FOUND` | 404 |
| `ERR_SITE_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_CREW_NOT_FOUND` | 404 |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 |
| `ERR_MATERIAL_NOT_FOUND` | 404 |
| `ERR_NOTICE_NOT_FOUND` | 404 |
| `ERR_COST_RECOVERY_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CREW_UNAVAILABLE` | 409 |
| `ERR_RECOVERY_NOT_ASSESSED` | 409 |
| `ERR_CURE_WINDOW_NOT_ELAPSED` | 409 |
| `ERR_CREW_NOT_CERTIFIED` | 422 |
| `ERR_CREW_SCHEDULE_CONFLICT` | 409 |
| `ERR_SITE_ABATEMENT_BUFFER_CONFLICT` | 409 |
| `ERR_BEFORE_PHOTO_REQUIRED` | 422 |
| `ERR_AFTER_PHOTO_REQUIRED` | 422 |
| `ERR_PRIVATE_SITE_REQUIRES_OWNER` | 422 |
| `ERR_STALE_SITE_VERSION` | 412 |
| `ERR_INSUFFICIENT_MATERIAL` | 409 |

# Ladder & Access Equipment Manufacturing API — Product Requirements Document

## 1. Introduction

A ladder manufacturer lives or dies by two records: the one that proves a rail was designed and tested to carry its declared duty rating, and the one that proves which consumer bought which unit out of which production lot. Today those records live in disconnected places — duty-rating calculations in a spreadsheet, third-party listing correspondence in an inbox, rivet pull-test coupons in a lab notebook, and recall contact data in a marketing database. When a rail fractures in the field, nobody can answer the only question that matters quickly enough: which lots are exposed, and are they still shipping?

This document specifies the Ladder & Access Equipment Manufacturing API, a single system of record that carries a product family from duty-rating design through load testing, extrusion and fiberglass pultrusion production, labelling and retail packaging, third-party certification listing with periodic audit testing of production samples, and — when something goes wrong in the field — incident investigation, design corrective action, and recall execution with lot-level traceability. All business resources are mounted under `/ladder-ops`.

The system is deliberately opinionated on two points. First, **compliance evidence gates commerce**: a model cannot be released to the retail channel until its design is frozen against an approved revision that passed a qualification campaign, until every mandated label and packaging document has been approved, and until a third-party body has actually listed it. Second, **containment is automatic and transitive**: quarantining a lot, suspending a listing, or failing a periodic audit must ripple outward to stop shipments, put consumer registrations on hold, cancel planned lab work, and release the bench minutes that work was holding — without an operator remembering to do each step by hand.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold for every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which that principal acts. If either header is absent, or if `X-User-Role` is not one of the nine role names below, the request is rejected with `ERR_UNAUTHENTICATED`. If the headers are well-formed but the supplied role is not listed among the target endpoint's authorized roles, the request is rejected with `ERR_ROLE_NOT_PERMITTED`.

The nine recognized roles are `DesignEngineer`, `DesignApprover`, `TestLabTechnician`, `ProductionSupervisor`, `ComplianceOfficer`, `CertificationBody`, `Consumer`, `SafetyDirector`, and `SystemOperator`.

- A `DesignEngineer` authors product models and design revisions and drafts label and packaging artwork.
- A `DesignApprover` reviews revisions, freezes designs, and verifies corrective actions.
- A `TestLabTechnician` owns the lab: benches, reservations, campaigns, load tests, and joint pull samples.
- A `ProductionSupervisor` runs extrusion, pultrusion, and assembly lots, may quarantine a lot, and may dispose of a quarantined lot only by releasing it.
- A `ComplianceOfficer` owns labelling approval, listing applications, retail release, and consumer notification duty.
- A `CertificationBody` is the third-party listing body that lists and suspends listing records.
- A `Consumer` is a retail purchaser who registers a unit, reports a field incident, and acknowledges a recall remedy.
- A `SafetyDirector` is the product-safety authority: investigations, scrap authority, resume-ship authority, and the recall lifecycle.
- A `SystemOperator` exists solely to drive the deterministic logical clock and holds no business permission.

**Identity semantics.** When `X-User-Role` is `CertificationBody`, `X-User-ID` is the `id` of the acting `ListingBody`; ownership checks on any resource that references a `ListingBody` compare the resource's `listing_body_id` to `X-User-ID`, so a certification body acting on a listing record whose `listing_body_id` is not its own `X-User-ID` is rejected with `ERR_LISTING_BODY_MISMATCH`. For the other eight roles — `DesignEngineer`, `DesignApprover`, `TestLabTechnician`, `ProductionSupervisor`, `ComplianceOfficer`, `Consumer`, `SafetyDirector`, and `SystemOperator` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example as `submitted_by_user_id` and `reviewed_by_user_id` on a design revision, or as `authored_by_user_id` and `verified_by_user_id` on a corrective action) but never compares it to any entity's `id`.

**Segregation of duties.** Two approval acts compare the caller's `X-User-ID` against a previously recorded operator identifier and reject a self-approval with `ERR_SEGREGATION_OF_DUTIES`: reviewing a design revision the caller submitted, and verifying a corrective action the caller authored. A third separation is enforced by role rather than by identity — scrapping a quarantined lot is reserved to a `SafetyDirector`, and a `ProductionSupervisor` who asks for that disposition is rejected with `ERR_SCRAP_REQUIRES_SAFETY_DIRECTOR` even though the same supervisor is authorized to quarantine the lot in the first place.

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

List endpoints accept two query parameters. `limit` sets the maximum number of rows returned; it defaults to 10, may be no smaller than 1, and may be no larger than 100. `offset` sets the number of rows skipped before the page begins; it defaults to 0 and must be a non-negative integer. A `limit` outside the range 1 through 100, or an `offset` that is negative or not an integer, is rejected with `ERR_INVALID_PAGINATION`.

Unless a specific endpoint states otherwise, every list endpoint returns rows sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Record Identity, Timestamps and the Logical Clock

Every persisted resource carries an `id`, which is a server-minted UUID with no type prefix, and a `created_at` timestamp formatted as ISO 8601 UTC with three fractional digits. Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that increments by one on every mutation — including mutations the server performs on its own initiative as part of a cascade, and including recomputation of derived fields such as a product's risk scores or a lot's unit buckets.

Two record types are append-only measurement records and therefore carry **only** `id` and `created_at`: a load test record and a joint integrity sample record. Neither has an `updated_at` field and neither has a `version` field. Once written they are never modified and are never excluded from any aggregate that reads them.

Every `*_at`, `*_until`, and `*_due_at` value in the system is derived from a deterministic **logical clock** rather than from wall-clock time. The clock starts at `2026-08-01T00:00:00Z` when the process starts, never advances on its own, and is moved only by a `SystemOperator` supplying a `to_iso8601` instant to the clock-setting capability, which answers with the resulting `current_utc`. Date arithmetic that adds days (a listing term, an audit interval, a recall window) adds exact 24-hour days to the clock reading; date arithmetic that adds years (design-history retention) is calendar-based, landing on the same month and day of the target year, with 29 February mapping to 1 March.

### 2.5. Request Resolution Order, Collection Filters and Uniqueness

Requests are evaluated against a fixed priority ladder, and the **first** failing check determines the response. Later checks never mask an earlier one.

1. Header authentication (`ERR_UNAUTHENTICATED`).
2. Role authorization against the endpoint's role list (`ERR_ROLE_NOT_PERMITTED`).
3. Existence of every identifier in the request **path**, validated left to right, answering with the not-found code of the first unresolvable segment: `ERR_PRODUCT_NOT_FOUND`, `ERR_DESIGN_REVISION_NOT_FOUND`, `ERR_PRODUCT_DOCUMENT_NOT_FOUND`, `ERR_TEST_BENCH_NOT_FOUND`, `ERR_BENCH_RESERVATION_NOT_FOUND`, `ERR_TEST_CAMPAIGN_NOT_FOUND`, `ERR_PRODUCTION_LOT_NOT_FOUND`, `ERR_LISTING_RECORD_NOT_FOUND`, `ERR_CONSUMER_REGISTRATION_NOT_FOUND`, `ERR_FIELD_INCIDENT_NOT_FOUND`, `ERR_CORRECTIVE_ACTION_NOT_FOUND`, or `ERR_RECALL_EVENT_NOT_FOUND`.
4. Existence of every foreign-key identifier in the request **body**, validated in the order the fields are declared for that operation, answering with `ERR_PRODUCT_NOT_FOUND`, `ERR_DESIGN_REVISION_NOT_FOUND`, `ERR_LISTING_BODY_NOT_FOUND`, `ERR_LISTING_RECORD_NOT_FOUND`, `ERR_PRODUCTION_LOT_NOT_FOUND`, `ERR_TEST_BENCH_NOT_FOUND`, `ERR_TEST_CAMPAIGN_NOT_FOUND`, `ERR_FIELD_INCIDENT_NOT_FOUND`, or `ERR_CORRECTIVE_ACTION_NOT_FOUND` as appropriate.
5. Listing-body ownership for the `CertificationBody` role on the listing and suspension operations (`ERR_LISTING_BODY_MISMATCH`).
6. Request-body shape on every creating or acting operation — required fields present, enum values drawn from their declared sets, numbers inside their declared ranges, datetimes valid ISO 8601 (`ERR_INVALID_REQUEST`).
7. Pagination bounds on every list operation (`ERR_INVALID_PAGINATION`).
8. Window ordering, where a window is supplied (`ERR_INVALID_WINDOW`).
9. Not-in-the-future checks on supplied consumer and incident instants (`ERR_DATE_IN_FUTURE`).
10. and 11. The two stale-version guards described in §2.8 (`ERR_STALE_PRODUCT_VERSION`, then `ERR_STALE_INCIDENT_VERSION`).
12. through 22. State-precondition checks, in this order: design revision (`ERR_REVISION_STATE_INVALID`), product document (`ERR_DOCUMENT_NOT_DRAFT`), test campaign (`ERR_CAMPAIGN_STATE_INVALID`), bench reservation (`ERR_RESERVATION_NOT_HELD`), production lot (`ERR_LOT_STATE_INVALID`), listing record (`ERR_LISTING_STATE_INVALID`), product (`ERR_PRODUCT_STATE_INVALID`), field incident (`ERR_INCIDENT_STATE_INVALID`), corrective action (`ERR_CORRECTIVE_ACTION_NOT_OPEN`), recall event (`ERR_RECALL_STATE_INVALID`), consumer registration (`ERR_REGISTRATION_NOT_NOTIFIED`).
23. through 25. The three separation-of-duty checks: revision self-review, corrective-action self-verification (both `ERR_SEGREGATION_OF_DUTIES`), and scrap authority (`ERR_SCRAP_REQUIRES_SAFETY_DIRECTOR`).
26. through 31. Manufacturing and labelling safety gates, in this order: `ERR_NO_JOINT_SAMPLES`, `ERR_JOINT_SAMPLE_COUNT_SHORT`, `ERR_JOINT_INTEGRITY_FAILURE`, `ERR_CONFORMANCE_BELOW_MINIMUM`, `ERR_LABEL_SET_INCOMPLETE`, `ERR_LABEL_PLACEMENT_INVALID`.
32. through 35. Referential-scope checks: `ERR_REVISION_PRODUCT_MISMATCH`, `ERR_AUDIT_SCOPE_MISMATCH`, `ERR_AUDIT_FIELDS_MISMATCH`, `ERR_SUPERSEDE_TARGET_MISMATCH`.
36. through 54. Business constraints, in this order: `ERR_REVISION_NOT_APPROVED`, `ERR_DESIGN_NOT_FROZEN`, `ERR_QUALIFYING_CAMPAIGN_MISSING`, `ERR_STANDARD_NOT_ACCREDITED`, `ERR_NO_ACTIVE_LISTING`, `ERR_BENCH_CAPACITY_INSUFFICIENT`, `ERR_PROCESS_TRACEABILITY_MISSING`, `ERR_PRODUCED_UNITS_INVALID`, `ERR_LOT_NOT_SHIPPABLE`, `ERR_REQUIRED_TESTS_MISSING`, `ERR_AUDIT_SAMPLE_SHORT`, `ERR_RISK_SCORE_ABOVE_THRESHOLD`, `ERR_QUARANTINE_HOLD_PRESENT`, `ERR_RECALL_ALREADY_OPEN`, `ERR_RECALL_SCOPE_EMPTY`, `ERR_RECALL_UNITS_OUTSTANDING`, `ERR_REMEDY_CHOICE_MISMATCH`, `ERR_FINDING_ROOT_CAUSE_MISMATCH`, `ERR_DESIGN_MARGIN_INSUFFICIENT`.
55. and 56. Temporal collision checks: bench occupancy (`ERR_BENCH_WINDOW_CONFLICT`) and audit-window overlap (`ERR_AUDIT_WINDOW_OVERLAP`).
57. Uniqueness (`ERR_DUPLICATE_KEY`).

**Uniqueness.** A product's `model_code`, a bench's `bench_code`, a listing body's `body_code`, and a production lot's `lot_code` are each globally unique across their own collection. A design revision's `revision_label` is unique within its `product_id`. A joint sample's `sample_seq` is unique within its `production_lot_id`. Any repeat is rejected with `ERR_DUPLICATE_KEY`.

**Collection filters.** Alongside `limit` and `offset`, each collection accepts optional equality filters. Products may be filtered by `frozen_revision_id`, `product_type`, `material`, `duty_rating`, `design_status`, and `market_status`. Design revisions accept `product_id`, `supersedes_revision_id`, `status`, and `joint_type`. A product's document collection accepts `doc_kind` and `status`. Bench reservations accept `test_bench_id`, `test_campaign_id`, and `status`. Test campaigns accept `product_id`, `design_revision_id`, `listing_record_id`, `sampled_lot_id`, `purpose`, and `status`, and a campaign's load tests accept `outcome` and `test_code`. Production lots accept `product_id`, `design_revision_id`, `status`, and `lot_code`, and a lot's joint samples accept `result`. Listing records accept `product_id`, `listing_body_id`, `status`, and `standard_code`. Consumer registrations accept `production_lot_id`, `recall_event_id`, `registration_status`, and `hold_flag`. Field incidents accept `product_id`, `production_lot_id`, `consumer_registration_id`, `status`, `incident_type`, and `injury_severity`. Corrective actions accept `field_incident_id`, `design_revision_id`, `supersedes_action_id`, and `status`. Recall events accept `product_id`, `status`, and `remedy_type`.

### 2.6. Engineering Precision and Rounding Discipline

All derived numeric values are rounded half up. Load and force figures — a product's `safety_factor`, `required_test_load_lb`, and `required_pull_force_lbf`, a lot's `conformance_index`, an incident's `incident_points`, a product's `risk_score_gross` and `risk_score_mitigated`, a campaign's `prior_failure_rate_pct`, and a recall's `notification_coverage_pct` — are stored to exactly two decimal places. A product's `max_allowed_deflection_in` is stored to exactly three decimal places. A joint sample's `margin_pct` is a whole number of percent, that is, zero decimal places. Unit counts, exposure figures, sample sizes, and reserved minutes are exact integers with no rounding at all.

Two rules governing *when* rounding happens are load-bearing, because rounding at the wrong step yields a different and non-conforming answer. First, in a nested expression, rounding happens once, at the end of that expression, except where a step is explicitly described as rounding per item. Second, when a value is reused downstream, the already-rounded value is what is reused: the rounded `safety_factor` is what multiplies the rated load, and each joint sample's already-rounded whole-percent `margin_pct` is what enters the lot average — the lot average is never taken over unrounded margins.

Comparisons never round. A load test's `applied_load_lb`, `measured_deflection_in`, and `permanent_set_in` are compared against their thresholds at the full declared precision of the stored values, with no intermediate rounding.

### 2.7. Two Independent Product Dimensions and Cascade Discipline

A product model carries **two independent status dimensions on the same record**. `design_status` tracks the engineering lifecycle through `DRAFT`, `DESIGN_FROZEN`, and the terminal `DESIGN_OBSOLETE`. `market_status` tracks the retail-channel lifecycle through `NOT_RELEASED`, `RETAIL_RELEASED`, `STOP_SHIP`, and the terminal `RECALLED`. The two dimensions move independently: freezing a design never changes `market_status`, and stopping or resuming shipment never changes `design_status`. Only a recall announcement moves both in one request.

`market_status` is additionally **cyclic** between `RETAIL_RELEASED` and `STOP_SHIP` — a model may be stopped and resumed any number of times. So is a listing record, which may travel `LISTED` → `SUSPENDED` → `LISTED` repeatedly, a production lot, which may travel `RELEASED` → `QUARANTINED` → `RELEASED`, and a design revision, whose review loop runs `DRAFT` → `UNDER_REVIEW` → `CHANGES_REQUESTED` → `DRAFT`.

Server-initiated transitions are as real as operator-initiated ones. When a cascade moves a resource, that resource's `updated_at` is refreshed and its `version` increments, exactly as if a client had acted on it directly. Each hop of a cascade is caused by the mutation the previous hop performed, not by the original request, and hop order is pinned wherever two hops would write the same field: for an audit failure, listing suspension is applied before lot quarantine, so the resulting `stop_ship_reason_code` is `LISTING_SUSPENDED` and never `LOT_QUARANTINE`. Guards are stated on the source state rather than the target, so a cascade that re-enters an already-applied transition is skipped and the chain terminates rather than looping. Where a cascade arm is described as system-triggered and its preconditions do not hold, that arm is silently skipped; the originating request still succeeds.

### 2.8. Stale-Version Guards on Design and Incident Writes

Exactly two write operations are guarded by optimistic concurrency control against a parent record's `version`, and both take a mandatory version field.

Creating a design revision requires `expected_product_version` in the request body, carrying the `version` of the parent product as the client last observed it. If that value does not equal the product's current `version`, the create is rejected with `ERR_STALE_PRODUCT_VERSION` and HTTP 412. This is the serialization point for design history: if another engineer has already added a revision that legitimately supersedes the prior approved revision, the current writer's view of the product's design history is stale and must be refreshed before writing. A successful create increments the product's `version` by one.

Creating a corrective action requires `expected_field_incident_version` in the request body, carrying the `version` of the parent field incident as the client last observed it. If that value does not equal the incident's current `version`, the create is rejected with `ERR_STALE_INCIDENT_VERSION` and HTTP 412. This is the serialization point for corrective action: if an earlier action has already moved the incident to `CAPA_OPENED`, a superseding action would legitimately replace it, so the current writer's view of the incident is stale. A successful create increments the incident's `version` by one.

No other operation in the system accepts a version field, and no other operation performs a version comparison.

### 2.9. Conserved Quantities

Two aggregates in the system are **conserved**, meaning the system guarantees an arithmetic identity between an aggregate and the rows that feed it after every single request.

A production lot's five unit counters satisfy the identity that `units_wip` plus `units_quarantined` plus `units_released` plus `units_scrapped` always equals `produced_units`. Every lot transition moves units between buckets; none creates or destroys them. Before production starts, `produced_units` is 0 and so are all four buckets.

A test bench's `reserved_minutes_total` always equals the sum of `duration_minutes` over the bench's reservations whose `status` is `HELD` or `CONSUMED`. Creating a reservation adds its `duration_minutes` to the bench total. Cancelling a `HELD` reservation subtracts that same `duration_minutes`, restoring the pre-reservation value exactly. Consuming a reservation leaves the total untouched, because a `CONSUMED` reservation remains inside the conserved sum.

### 2.10. Design-History Retention and the Liability Dossier

Product liability documentation must outlive the product. Each product therefore carries `dhf_retention_until`, the instant its design history file may be discarded, and `retention_anchor_source`, naming which event supplied the anchor. Both are null until the design is frozen, and both are recomputed on design freeze, on lot release, when a field incident closes through corrective-action verification, and on recall announcement.

The computation considers four candidate instants, each with its own status filter. The **lot-release candidate** is the latest `released_at` across the product's lots whose `status` is `RELEASED` or `QUARANTINED` and whose `released_at` is set; lots that are `OPEN`, `IN_PROCESS`, or `SCRAPPED` never contribute. The **incident-closure candidate** is the latest `closed_at` across the product's field incidents whose `status` is `CLOSED` and whose `closed_at` is set; incidents in any other status, including `NOT_SUBSTANTIATED`, never contribute. The **recall candidate** is the product's `market_status_changed_at`, but only while `market_status` is `RECALLED`; otherwise there is no recall candidate. The **design-freeze candidate** is the product's `design_frozen_at`.

If the design-freeze candidate is null, both `dhf_retention_until` and `retention_anchor_source` are null. Otherwise the anchor is the latest of the candidates that are not null, and `dhf_retention_until` is that anchor plus seven calendar years. When two or more candidates are exactly equal to the anchor, `retention_anchor_source` is decided by a fixed precedence: `LOT_RELEASE` first, then `INCIDENT_CLOSURE`, then `RECALL`, then `DESIGN_FREEZE`. On a product with no lots, no closed incidents, and no recall, the anchor is `design_frozen_at` and `retention_anchor_source` is `DESIGN_FREEZE`.

A consolidated **liability dossier** read is available for a product to a `ComplianceOfficer` or a `SafetyDirector`. It answers with `product_id`, `model_code`, `design_history_revision_count` (how many design revisions exist for the model), `approved_document_kinds` (the distinct `doc_kind` values that currently have an approved document), `passed_campaign_count` (how many of the model's test campaigns are in `PASSED`), `released_lot_count` (how many of the model's lots are in `RELEASED`), `open_incident_count` (how many of the model's field incidents have not yet reached a terminal status, that is, are neither `NOT_SUBSTANTIATED` nor `CLOSED`), `risk_score_gross`, `risk_score_mitigated`, `dhf_retention_until`, and `retention_anchor_source`.

## 3. Business Logic & Workflows

### 3.1. Cataloguing a Model and Deriving Its Load Requirements

A `DesignEngineer` opens the catalogue entry for a new ladder by supplying a `model_code` of between 1 and 40 characters, a `product_type`, a `material`, a `duty_rating`, a `working_length_ft`, and the `retail_sku` that will be printed on the carton. `product_type` is one of `STEP_LADDER`, `EXTENSION_LADDER`, `PLATFORM_LADDER`, `ARTICULATED_LADDER`, or `MOBILE_SCAFFOLD_TOWER`. `material` names the primary rail construction process and is one of `ALUMINUM_EXTRUSION`, `FIBERGLASS_PULTRUSION`, or `STEEL`. `duty_rating` is the declared duty class and is one of `TYPE_III`, `TYPE_II`, `TYPE_I`, `TYPE_IA`, or `TYPE_IAA`. `working_length_ft` is the maximum working length in feet, recorded to one decimal place; it must be greater than zero and no greater than 60 feet.

Creation is where the model's entire test contract is fixed, and because there is no update operation for a catalogue entry, these derived figures are immutable for the life of the model. The derivation runs in four steps.

**Step one — the duty class picks the rated working load.** `rated_load_lb` is 200 pounds for `TYPE_III`, 225 for `TYPE_II`, 250 for `TYPE_I`, 300 for `TYPE_IA`, and 375 for `TYPE_IAA`.

**Step two — length buys safety-factor steps.** Subtract the twelve-foot baseline from `working_length_ft`, divide the remainder by four feet, and round the quotient **up** to the next whole number; if the result is negative, use zero. Rounding up means a twelve-foot ladder buys no step at all, while a ladder of twelve feet and one tenth already buys a full step, and a twenty-foot ladder buys two.

**Step three — three adders combine, then a cap clamps them.** Start from a base safety factor of 4.00. Add fifteen hundredths for each length step counted in step two. Add the product-family bonus: nothing for `STEP_LADDER`, `EXTENSION_LADDER`, or `PLATFORM_LADDER`, one tenth for `ARTICULATED_LADDER`, and one quarter for `MOBILE_SCAFFOLD_TOWER`. Add five hundredths when `material` is `FIBERGLASS_PULTRUSION`, and nothing for the other two materials. Whichever is smaller — that sum or the hard ceiling of 4.60 — becomes `safety_factor`, rounded half up to two decimal places.

**Step four — three requirements fall out.** `required_test_load_lb` is `rated_load_lb` multiplied by the already-rounded `safety_factor`, the product rounded half up to two decimal places; this is the load a qualifying static test must reach. `required_pull_force_lbf` is `rated_load_lb` multiplied by one and a half, rounded half up to two decimal places; this is the minimum joint pull force each production sample must survive. `max_allowed_deflection_in` is `working_length_ft` converted to inches by multiplying by twelve, then divided by the span divisor of 180, the result rounded half up to three decimal places; this is the deflection ceiling for a passing load test.

A newly catalogued model starts with `design_status` at `DRAFT`, `market_status` at `NOT_RELEASED`, `held_registration_count` at 0, `risk_score_gross` and `risk_score_mitigated` both at 0.00, and `design_frozen_at`, `frozen_revision_id`, `market_status_changed_at`, `stop_ship_reason_code`, `dhf_retention_until`, and `retention_anchor_source` all null.

### 3.2. The Design Revision Review Cycle

Engineering detail lives on a **design revision**, created by a `DesignEngineer` with a payload naming the `product_id`, a `revision_label` unique within that model, a `joint_type`, a `structural_margin_pct`, a `rail_section_modulus_in3`, and the mandatory `expected_product_version` described in §2.8. `joint_type` is the rail-to-rung joining process and is one of `RIVETED`, `BONDED`, or `WELDED`. `structural_margin_pct` is the predicted structural margin over the duty rating expressed in percent, must be zero or greater, and is recorded to two decimal places. `rail_section_modulus_in3` is the rail section modulus in cubic inches, must be greater than zero, and is recorded to three decimal places. An optional `supersedes_revision_id` names the prior revision this one replaces and is null for a model's first revision; if it names a revision belonging to a different model, the create is rejected with `ERR_SUPERSEDE_TARGET_MISMATCH`. A new revision begins at `status` `DRAFT` with `review_round` at 1, and with `submitted_by_user_id`, `reviewed_by_user_id`, `reviewer_notes`, and `superseded_at` all null.

Submitting the revision for review moves it `DRAFT` → `UNDER_REVIEW` and stamps `submitted_by_user_id` with the submitting engineer's `X-User-ID`, and it also increments the revision's `version`. Submission is gated on the predicted margin: a `structural_margin_pct` below 2.00 percent is rejected with `ERR_DESIGN_MARGIN_INSUFFICIENT`. A revision that is not in `DRAFT` when submission is requested is rejected with `ERR_REVISION_STATE_INVALID`, and the same code answers a review decision on a revision that is not `UNDER_REVIEW` and a revise request on a revision that is not `CHANGES_REQUESTED`.

A `DesignApprover` decides an `UNDER_REVIEW` revision by supplying a `decision` of either `APPROVE` or `REQUEST_CHANGES`, optionally with `reviewer_notes`. Either decision stamps `reviewed_by_user_id` with the reviewer's `X-User-ID` and stores the supplied `reviewer_notes`. Both decisions are blocked with `ERR_SEGREGATION_OF_DUTIES` when the reviewer's `X-User-ID` equals the revision's `submitted_by_user_id`.

The two decisions then diverge symmetrically. `REQUEST_CHANGES` moves the revision `UNDER_REVIEW` → `CHANGES_REQUESTED` and imposes no engineering threshold. `APPROVE` moves the revision `UNDER_REVIEW` → `APPROVED`, but only if `rail_section_modulus_in3` is at least 0.180 cubic inches; below that the approval is rejected with `ERR_DESIGN_MARGIN_INSUFFICIENT`. Approval also carries one cascade: if this revision names a `supersedes_revision_id` and the revision so named is itself in `APPROVED`, that older revision moves `APPROVED` → `SUPERSEDED` and its `superseded_at` is stamped with the logical clock. `SUPERSEDED` is terminal for a revision. A consequence reaches into production immediately — any lot still `OPEN` that pinned the now-superseded revision can no longer start production, because the pinned revision must be `APPROVED` with a null `superseded_at`, and a pinned revision that fails either half of that test is rejected with `ERR_REVISION_NOT_APPROVED`.

Closing the loop, a revision in `CHANGES_REQUESTED` is revised back to `DRAFT` by a `DesignEngineer`. Revising increments `review_round` by one, so `review_round` is the count of completed review loops, and it clears `submitted_by_user_id` back to null so that the next submission re-stamps it with whoever submits. Any of `structural_margin_pct`, `rail_section_modulus_in3`, and `joint_type` supplied with the revise request overwrite the stored engineering values; values not supplied are left as they were.

Every operation that pins a revision to a model checks that the two agree. When the revision named by `design_revision_id` — or by `frozen_revision_id` at design freeze — belongs to a different model than the one in the request, the operation is rejected with `ERR_REVISION_PRODUCT_MISMATCH`.

### 3.3. Labelling, Warnings and Retail Packaging Artwork

Standards dictate not merely that a ladder be labelled but *what* the label says and *where* it sits. A **product document** is created by a `DesignEngineer` or a `ComplianceOfficer` with a payload naming the `product_id`, a `doc_kind`, a `document_version` for the artwork revision, and a `text_digest` — a digest of the approved wording, held so that silent text changes are detectable. Three further fields are optional in the payload: `placement_zone`, `pictogram_count`, which defaults to 0, and `includes_assembly_instructions`, which defaults to false. Documents begin at `status` `DRAFT` with `approved_at` null.

`doc_kind` is one of seven values. The first four — `DUTY_RATING_LABEL`, `WARNING_LABEL`, `INSTRUCTION_LABEL`, and `CERT_MARK_LABEL` — are **label kinds** that go on the ladder itself and therefore require a `placement_zone`, which is one of `SIDE_RAIL_UPPER`, `SIDE_RAIL_LOWER`, `TOP_CAP`, or `BACK_RAIL`. The remaining three — `RETAIL_CARTON`, `ASSEMBLY_INSTRUCTION_SHEET`, and `CONSUMER_SAFETY_SHEET` — are packaging and paperwork kinds and must carry a null `placement_zone`.

Three artwork rules are enforced identically at document creation and again at approval, and any of the three failing yields `ERR_LABEL_PLACEMENT_INVALID`: a label kind must have a non-null `placement_zone` while a non-label kind must have a null one; a `WARNING_LABEL` must carry at least two warning pictograms in its `pictogram_count`; and an `ASSEMBLY_INSTRUCTION_SHEET` must have `includes_assembly_instructions` set to true. Checking at both moments matters, because approval is the gate the retail-release check reads.

Approval belongs to a `ComplianceOfficer` and moves the document `DRAFT` → `APPROVED`, stamping `approved_at` with the logical clock. Approval also supersedes: any other document for the same model with the same `doc_kind` that was in `APPROVED` moves `APPROVED` → `SUPERSEDED`, which is terminal. A superseded document no longer satisfies the mandated-document gate on retail release, so replacing artwork never leaves two live versions of the same kind. Approval requested on a document that is already `APPROVED` or `SUPERSEDED` is rejected with `ERR_DOCUMENT_NOT_DRAFT`.

### 3.4. The Test Lab: Bench Occupancy, Campaign Execution and Load Verdicts

Load testing runs on physical benches. A `TestLabTechnician` registers a **test bench** with a globally unique `bench_code`, a `max_load_capacity_lb` greater than zero, and a `cooldown_minutes` buffer between zero and 480 minutes — up to eight hours of mandatory recovery appended after each reservation before the bench may be re-occupied. A new bench starts with `reserved_minutes_total` at 0.

A **bench reservation** names the `test_bench_id` it occupies, the `test_campaign_id` that will consume it, an inclusive `start_at`, and an exclusive `end_at`. The reservation begins at `status` `HELD`, its `duration_minutes` is set to the whole number of minutes between `start_at` and `end_at`, and that figure is added to the bench's `reserved_minutes_total` per §2.9. A reservation whose `start_at` is not strictly earlier than its `end_at` is rejected with `ERR_INVALID_WINDOW`.

Occupancy conflicts use half-open intervals extended by the bench's own cooldown. A new reservation is rejected with `ERR_BENCH_WINDOW_CONFLICT` when the same bench already carries a reservation in `HELD` or `CONSUMED` such that the new `start_at` is strictly earlier than that existing reservation's `end_at` advanced by the bench's `cooldown_minutes`, **and** the new `end_at` is strictly later than that existing reservation's `start_at`. Because the comparison against the extended end is strict, a new reservation starting exactly at the moment the cooldown expires is accepted; because the comparison against the existing start is also strict, a new reservation ending exactly when an existing one begins is accepted. Reservations in `CANCELLED` are ignored by the conflict check entirely. Cancelling a `HELD` reservation moves it `HELD` → `CANCELLED` and subtracts its `duration_minutes` from the bench's `reserved_minutes_total`; cancellation requested on a reservation that is already `CONSUMED` or `CANCELLED` is rejected with `ERR_RESERVATION_NOT_HELD`.

A **test campaign** is the cross-cutting record that ties a model, a revision, a listing, and a lot together. A `TestLabTechnician` or a `ComplianceOfficer` plans one with a payload naming the `product_id`, the `design_revision_id` the campaign qualifies, and a `purpose` of `DESIGN_QUALIFICATION`, `CERTIFICATION_LISTING`, `PERIODIC_AUDIT`, or `INCIDENT_INVESTIGATION`. Four further fields — `listing_record_id`, `sampled_lot_id`, `sample_window_start`, and `sample_window_end` — belong exclusively to the audit purpose and are covered in §3.5. A campaign begins at `status` `PLANNED` with `load_test_count` and `failed_test_count` both at 0 and with `started_at` and `concluded_at` null. When a sample window is supplied, a `sample_window_start` that is not strictly earlier than its `sample_window_end` is rejected with `ERR_INVALID_WINDOW`.

Starting a campaign moves it `PLANNED` → `IN_PROGRESS`, stamps `started_at` with the logical clock, and consumes a bench slot. The technician supplies a `bench_reservation_id`; that reservation must belong to this campaign by its `test_campaign_id` and must still be `HELD`, otherwise the start is rejected with `ERR_RESERVATION_NOT_HELD`. The reserved bench must also be able to reach the model's requirement: when the bench's `max_load_capacity_lb` is below the model's `required_test_load_lb`, the start is rejected with `ERR_BENCH_CAPACITY_INSUFFICIENT`. On success the named reservation moves `HELD` → `CONSUMED`, and the bench's `reserved_minutes_total` does not change. A campaign that is not `PLANNED` when a start is requested — and a campaign that is not `IN_PROGRESS` when a load test is recorded or a conclusion is requested — is rejected with `ERR_CAMPAIGN_STATE_INVALID`.

Each **load test** recorded against an `IN_PROGRESS` campaign carries a `test_code`, the `applied_load_lb` actually applied (greater than zero, two decimal places), the peak `measured_deflection_in` under load (zero or greater, three decimal places), and the `permanent_set_in` remaining after the load is removed (zero or greater, three decimal places). `test_code` is one of `STATIC_VERTICAL`, `RAIL_BENDING`, `SLIP_RESISTANCE`, `HINGE_CYCLE`, `ELECTRICAL_LEAKAGE`, or `RIVET_SHEAR`. The verdict is derived, never supplied, and three criteria are evaluated in a fixed order with the **first** failure recorded as the `failure_reason_code`:

1. If `applied_load_lb` is less than the model's `required_test_load_lb`, the `outcome` is `FAIL` with `failure_reason_code` `LOAD_BELOW_REQUIRED`.
2. Otherwise, if `measured_deflection_in` is greater than the model's `max_allowed_deflection_in`, the `outcome` is `FAIL` with `failure_reason_code` `DEFLECTION_EXCEEDED`.
3. Otherwise, if `permanent_set_in` is greater than twenty thousandths of an inch, the `outcome` is `FAIL` with `failure_reason_code` `PERMANENT_SET_EXCEEDED`.
4. Otherwise the `outcome` is `PASS` and `failure_reason_code` is null.

Every comparison is inclusive on the passing side, so a test that exactly meets the required load, exactly reaches the deflection ceiling, and exactly reaches the permanent-set ceiling passes. After each insert, the campaign's `load_test_count` is recounted as the number of load test rows on the campaign regardless of outcome, and `failed_test_count` as the number whose `outcome` is `FAIL`.

Concluding a campaign requires evidence coverage first, and the coverage requirement applies before a verdict of **either** polarity — a campaign cannot be failed out of an incomplete test matrix any more than it can be passed out of one. For a campaign whose `purpose` is `DESIGN_QUALIFICATION`, `CERTIFICATION_LISTING`, or `INCIDENT_INVESTIGATION`, every `test_code` in the campaign's required test-code set must have at least one load test row on the campaign; a missing code is rejected with `ERR_REQUIRED_TESTS_MISSING`. The required set is determined by the model's `product_type`, extended with `RIVET_SHEAR` whenever the campaign's pinned design revision has `joint_type` `RIVETED` — the pinned revision, not the model's current one, is what decides this. For a `PERIODIC_AUDIT` campaign the coverage rule is replaced by the sample-size rule in §3.5.

Once coverage holds, the verdict follows the failure count: a campaign with `failed_test_count` equal to 0 moves `IN_PROGRESS` → `PASSED`, and a campaign with `failed_test_count` greater than 0 moves `IN_PROGRESS` → `FAILED`. Either way `concluded_at` is stamped with the logical clock. `PASSED`, `FAILED`, and `CANCELLED` are all terminal for a campaign. The audit-specific consequences of both verdicts are described in §3.5.

### 3.5. Certification Listing and Periodic Audit Escalation

A `ComplianceOfficer` registers a third-party **listing body** with a globally unique `body_code`, a non-empty `accredited_standards` array whose members are drawn from `ANSI_ASC_A14_2`, `ANSI_ASC_A14_5`, `EN_131_2`, and `CSA_Z11`, and an `audit_interval_days` greater than zero and no greater than 730 — the number of days between periodic production-sample audits for records that body holds. The same officer then files a **listing record** naming the `product_id`, the `listing_body_id` of the body that will own the listing, and the `standard_code` the model is to be listed against. A filed record begins at `status` `APPLIED` with `listed_at`, `audit_due_at`, `listing_expires_at`, `suspended_at`, and `suspension_reason` all null.

Only the owning body may act on the record, per the ownership rule in §2.1. Granting the listing moves it `APPLIED` → `LISTED` and is gated on four things: the record must be `APPLIED`, or the request is rejected with `ERR_LISTING_STATE_INVALID`; the record's `standard_code` must be a member of the owning body's `accredited_standards`, or the request is rejected with `ERR_STANDARD_NOT_ACCREDITED`; the model's `design_status` must be `DESIGN_FROZEN`, or the request is rejected with `ERR_DESIGN_NOT_FROZEN`; and there must exist at least one test campaign for that model, pinned to the model's `frozen_revision_id`, with `purpose` `CERTIFICATION_LISTING` and `status` `PASSED`, or the request is rejected with `ERR_QUALIFYING_CAMPAIGN_MISSING`. On success three instants are stamped: `listed_at` at the logical clock, `audit_due_at` at the logical clock advanced by the owning body's `audit_interval_days`, and `listing_expires_at` at the logical clock advanced by the listing term of 1825 days — five 365-day years.

The owning body may suspend a `LISTED` record by supplying a `suspension_reason` of `AUDIT_FAILURE`, `STOP_SHIP_CASCADE`, or `BODY_REQUEST`; suspension of a record that is not `LISTED` is rejected with `ERR_LISTING_STATE_INVALID`. Suspension moves the record `LISTED` → `SUSPENDED`, stamps `suspended_at` with the logical clock, records the reason, and clears `audit_due_at` to null — a suspended listing has no audit deadline. It also cascades one hop: when the model's `market_status` is `RETAIL_RELEASED`, that model moves `RETAIL_RELEASED` → `STOP_SHIP` with `stop_ship_reason_code` set to `LISTING_SUSPENDED`, dragging the stop-ship consequences of §3.7 with it; when the model is already `STOP_SHIP` or `RECALLED`, this hop is skipped and the chain terminates there. Restoring a suspended listing to `LISTED` is never a direct operator act: it happens only as a system cascade in the same request in which the model returns from `STOP_SHIP` to `RETAIL_RELEASED`, at which point `suspended_at` and `suspension_reason` are cleared to null and `audit_due_at` is re-stamped at the logical clock advanced by the owning body's `audit_interval_days`. That closes the `LISTED` → `SUSPENDED` → `LISTED` cycle.

**Periodic audits.** An audit campaign is a test campaign whose `purpose` is `PERIODIC_AUDIT`, and it is the only purpose that takes the four audit fields. `PERIODIC_AUDIT` requires all four of `listing_record_id`, `sampled_lot_id`, `sample_window_start`, and `sample_window_end` to be present, while every other purpose requires all four to be null; a mismatch either way is rejected with `ERR_AUDIT_FIELDS_MISMATCH`. `sampled_lot_id` names the production lot the audit units were drawn from and `listing_record_id` names the listing being audited; if either the named listing record or the named lot belongs to a different model than the campaign's `product_id`, the plan is rejected with `ERR_AUDIT_SCOPE_MISMATCH`.

Audit sample windows on the same listing record must not overlap, and here the interval arithmetic is **closed on both ends with no buffer applied**, unlike bench occupancy. A new audit campaign is rejected with `ERR_AUDIT_WINDOW_OVERLAP` when the same `listing_record_id` already carries an audit campaign in `PLANNED`, `IN_PROGRESS`, `PASSED`, or `FAILED` such that the new `sample_window_start` is earlier than **or equal to** that campaign's `sample_window_end` and the new `sample_window_end` is later than **or equal to** that campaign's `sample_window_start`. Touching endpoints therefore do collide. Campaigns in `CANCELLED` are excluded from the check.

How many units the audit must test escalates from the *previous* audit's performance, and the evaluation order is pinned precisely because a failure rate is failures over sample size — the quantity being derived. The tier is always keyed on the prior concluded audit's own `audit_sample_size`, never on this campaign's.

1. Select the prior audit deterministically. Consider only campaigns on the **same** `listing_record_id` whose `purpose` is `PERIODIC_AUDIT` and whose `status` is `PASSED` or `FAILED`; campaigns that are `PLANNED`, `IN_PROGRESS`, or `CANCELLED` are excluded, as are campaigns of any other purpose and campaigns on any other listing record. Order the survivors by `sample_window_end` descending, breaking ties by `created_at` descending, and take the first. If there are none, there is no prior audit.
2. Derive `prior_failure_rate_pct`. With no prior audit it is null. Otherwise it is the prior campaign's `failed_test_count` divided by the prior campaign's `audit_sample_size`, expressed as a percentage, rounded half up to two decimal places.
3. Select `escalation_tier` with tier boundaries **inclusive on the upper edge**. It is `TIER_0` when there is no prior audit or when `prior_failure_rate_pct` is exactly 0.00. Otherwise it is `TIER_1` when `prior_failure_rate_pct` is 20.00 or less, `TIER_2` when it is 40.00 or less, and `TIER_3` above that.
4. Only now is this campaign's own `audit_sample_size` well-defined: it is the base audit sample of 5 units plus the tier adder — nothing for `TIER_0`, three more units for `TIER_1`, eight more for `TIER_2`, and fifteen more for `TIER_3`. The result is an exact integer.

For campaigns of any purpose other than `PERIODIC_AUDIT`, all three of `audit_sample_size`, `escalation_tier`, and `prior_failure_rate_pct` remain null.

Concluding an audit campaign substitutes the sample-size rule for the test-coverage rule: the campaign's `load_test_count` must be at least its `audit_sample_size`, and a short audit is rejected with `ERR_AUDIT_SAMPLE_SHORT`. An audit that concludes `PASSED` re-stamps the linked listing record's `audit_due_at` at the logical clock advanced by the owning body's `audit_interval_days`, resetting the audit clock.

An audit that concludes `FAILED` is the system's most consequential single act, and its four hops run in a pinned order. **Hop one:** the linked listing record moves `LISTED` → `SUSPENDED` with `suspension_reason` set to `AUDIT_FAILURE` and `audit_due_at` cleared to null. **Hop two,** caused by hop one: because a listed listing of the model became suspended, the model moves `RETAIL_RELEASED` → `STOP_SHIP` with `stop_ship_reason_code` set to `LISTING_SUSPENDED`. **Hop three,** caused by hop two and applicable only to the audit purpose: the lot named by `sampled_lot_id`, if its `status` is `IN_PROCESS` or `RELEASED`, moves to `QUARANTINED` with `quarantine_reason_code` set to `AUDIT_FAILURE`, and that quarantine's own first hop sets `hold_flag` on the lot's consumer registrations in `REGISTERED` or `NOTIFIED`; since the model is already `STOP_SHIP` by this point, the quarantine chain's reason-code reassignment to `LOT_QUARANTINE` is skipped and the chain terminates on the model. That ordering is why an audit failure always reads `LISTING_SUSPENDED` and never `LOT_QUARANTINE`. **Hop four,** also caused by hop two: because the model entered `STOP_SHIP`, every other test campaign of that model still in `PLANNED` moves `PLANNED` → `CANCELLED`, and each of those campaigns' reservations still in `HELD` moves `HELD` → `CANCELLED` with its `duration_minutes` subtracted from its bench's `reserved_minutes_total`.

### 3.6. Production Lots, Joint Integrity Sampling, Release and Quarantine

A `ProductionSupervisor` opens a **production lot** with a payload naming the `product_id` being built, the `design_revision_id` pinned to the lot at creation, a globally unique `lot_code` for traceability, and a `planned_units` count greater than zero. Two process-traceability fields are optional at creation: `extrusion_heat_number` records the aluminium extrusion heat and is null for non-extruded materials, and `pultrusion_batch_id` records the fiberglass pultrusion batch. A pinned revision belonging to a different model is rejected with `ERR_REVISION_PRODUCT_MISMATCH`. A new lot begins at `status` `OPEN` with `produced_units`, `units_wip`, `units_quarantined`, `units_released`, and `units_scrapped` all 0, with `joint_sample_count`, `joint_fail_count`, and `required_joint_sample_count` all 0, with `conformance_index` null, and with `released_at`, `quarantine_reason_code`, and `disposition` null.

Starting production moves the lot `OPEN` → `IN_PROCESS` and takes a single `produced_units` figure recording how many units were actually built. Four gates apply. The pinned revision must be `APPROVED` and not yet superseded, or the request is rejected with `ERR_REVISION_NOT_APPROVED`. The model's `design_status` must be `DESIGN_FROZEN`, or the request is rejected with `ERR_DESIGN_NOT_FROZEN` — which is also what a model already advanced to `DESIGN_OBSOLETE` receives, so no lot may start production for a recalled model. Process traceability must match the construction process: a lot of a model whose `material` is `FIBERGLASS_PULTRUSION` must carry a non-null `pultrusion_batch_id`, and a lot of a model whose `material` is `ALUMINUM_EXTRUSION` must carry a non-null `extrusion_heat_number`; either gap is rejected with `ERR_PROCESS_TRACEABILITY_MISSING`. And the supplied `produced_units` must be greater than zero and no greater than the lot's `planned_units`, or the request is rejected with `ERR_PRODUCED_UNITS_INVALID`. On success, both `produced_units` and `units_wip` are set to the supplied figure, and `required_joint_sample_count` is derived as the larger of four samples and the lot's `produced_units` divided by 250 units per sample rounded **up** to a whole number; while `produced_units` is 0 the required count stays 0. A lot in the wrong state for the requested step — anything but `OPEN` for starting production, anything but `IN_PROCESS` for recording joint samples or releasing, anything but `IN_PROCESS` or `RELEASED` for quarantine, anything but `QUARANTINED` for disposition — is rejected with `ERR_LOT_STATE_INVALID`.

**Joint integrity samples** are the rivet and joint pull records that qualify a lot. A `TestLabTechnician` or a `ProductionSupervisor` records one against an `IN_PROCESS` lot with a `sample_seq` greater than zero and unique within the lot, and a measured `pull_force_lbf` greater than zero recorded to two decimal places. Each sample snapshots the model's `required_pull_force_lbf` at insert time into its own `required_pull_force_lbf`, so later changes elsewhere cannot rewrite history, and its `result` is `PASS` when the measured `pull_force_lbf` is greater than or equal to that snapshot and `FAIL` otherwise.

The standard reports each sample's margin as a whole percent, so **the rounding happens once per sample and the already-rounded integers are what get averaged**. Each sample's `margin_pct` is the measured `pull_force_lbf` minus its snapshot requirement, divided by that snapshot requirement, expressed as a percentage, rounded half up to a whole number. The lot's `conformance_index` is then the arithmetic mean of those whole-percent integers across every sample on the lot, rounded half up to two decimal places. Averaging the unrounded margins and rounding once at the end is a different and non-conforming result. Every sample on the lot participates, ordered by `sample_seq` ascending, with no status filter of any kind — samples are immutable and are never excluded. When a lot has no samples at all, `conformance_index` is **null**, not 0.00. After each insert the lot's `joint_sample_count` is recounted as the number of sample rows and `joint_fail_count` as the number whose `result` is `FAIL`.

Releasing a lot to the retail channel moves it `IN_PROCESS` → `RELEASED` and clears four sampling gates, evaluated in this order. The lot must have at least one sample, or the release is rejected with `ERR_NO_JOINT_SAMPLES` — this is the empty-collection edge, where `conformance_index` is null rather than zero. Its `joint_sample_count` must be at least its `required_joint_sample_count`, or the release is rejected with `ERR_JOINT_SAMPLE_COUNT_SHORT`. Its `joint_fail_count` must be exactly 0, or the release is rejected with `ERR_JOINT_INTEGRITY_FAILURE`. And its `conformance_index` must be at least 2.00, or the release is rejected with `ERR_CONFORMANCE_BELOW_MINIMUM`. On success the whole `units_wip` bucket moves into `units_released`, leaving `units_wip` at 0 and the conserved identity of §2.9 intact; `released_at` is stamped with the logical clock if it is currently null and is otherwise left alone, so it survives later quarantine cycles as the lot's first-shipment instant; and the model's `dhf_retention_until` and `retention_anchor_source` are recomputed, with `retention_anchor_source` becoming `LOT_RELEASE` when this `released_at` is the latest candidate.

**Quarantine** is available to a `ProductionSupervisor`, a `ComplianceOfficer`, or a `SafetyDirector` on a lot in either `IN_PROCESS` or `RELEASED`, and also fires as a system cascade when an audit campaign on the lot concludes `FAILED`. Whichever from-state the lot was in, both `units_wip` and `units_released` move into `units_quarantined`, leaving the conserved sum unchanged, and `quarantine_reason_code` is set to the supplied `reason_code` — one of `JOINT_INTEGRITY`, `LABEL_DEFECT`, `AUDIT_FAILURE`, or `FIELD_INCIDENT` — or to `AUDIT_FAILURE` when the system triggered it.

Quarantine then drives a **five-hop transitive chain**, each hop caused by the mutation the preceding hop performed rather than by the original request. **Hop one:** every consumer registration whose `production_lot_id` is this lot and whose `registration_status` is `REGISTERED` or `NOTIFIED` has `hold_flag` set to true. **Hop two,** caused by hop one: because registrations were flagged, the model's `held_registration_count` is recomputed as the number of its registrations with `hold_flag` true, and when that count becomes greater than 0 while the model's `market_status` is `RETAIL_RELEASED`, the model moves `RETAIL_RELEASED` → `STOP_SHIP` with `stop_ship_reason_code` set to `LOT_QUARANTINE`. **Hop three,** caused by hop two: because the model entered `STOP_SHIP`, every listing record of the model in `LISTED` moves `LISTED` → `SUSPENDED` with `suspension_reason` set to `STOP_SHIP_CASCADE` and `audit_due_at` cleared to null. **Hop four,** also caused by hop two: every test campaign of the model still in `PLANNED` moves `PLANNED` → `CANCELLED`, whether or not it names a `listing_record_id`. **Hop five,** caused by hop four: each cancelled campaign's reservations still in `HELD` move `HELD` → `CANCELLED`, and each one's `duration_minutes` is subtracted from its bench's `reserved_minutes_total`.

**Disposition** closes out a quarantined lot and takes a single `disposition` of `RELEASE` or `SCRAP`. Choosing `RELEASE` is the compensating action for quarantine: it moves the lot `QUARANTINED` → `RELEASED`, moves the whole `units_quarantined` bucket back into `units_released` and so restores the pre-quarantine bucket split exactly, sets `disposition` to `RELEASE`, clears `quarantine_reason_code` to null, clears `hold_flag` to false on every consumer registration of the lot, and recomputes the model's `held_registration_count`. It repeats the release-quality gates: `joint_fail_count` must be exactly 0 or the disposition is rejected with `ERR_JOINT_INTEGRITY_FAILURE`, and `conformance_index` must be at least 2.00 or it is rejected with `ERR_CONFORMANCE_BELOW_MINIMUM`. That closes the `RELEASED` → `QUARANTINED` → `RELEASED` cycle.

Choosing `SCRAP` is reserved to a `SafetyDirector`, and a `ProductionSupervisor` who asks for it is rejected with `ERR_SCRAP_REQUIRES_SAFETY_DIRECTOR` even though that supervisor is authorized to reach the disposition operation at all. Scrapping moves the lot `QUARANTINED` → `SCRAPPED`, which is terminal, moves the whole `units_quarantined` bucket into `units_scrapped` with the conserved sum unchanged, sets `disposition` to `SCRAP`, clears `hold_flag` to false on every consumer registration of the lot, and recomputes the model's `held_registration_count`. Because a scrapped lot never shipped in the eyes of the recall accounting, it leaves every recall exposure basis described in §3.9.

### 3.7. Design Freeze, Retail Release and the Ship / Stop-Ship Cycle

Freezing a design is the act that converts an engineering file into a manufacturing licence, and it belongs to a `DesignApprover`, who supplies the `frozen_revision_id` to pin. Three conditions hold. The model's `design_status` must be `DRAFT`, or the request is rejected with `ERR_PRODUCT_STATE_INVALID`. The named revision must belong to this model — otherwise `ERR_REVISION_PRODUCT_MISMATCH` — and must be `APPROVED` and not superseded, otherwise `ERR_REVISION_NOT_APPROVED`. And at least one test campaign must exist for this model, pinned to exactly the revision being frozen, with `purpose` `DESIGN_QUALIFICATION` and `status` `PASSED`; without it the freeze is rejected with `ERR_QUALIFYING_CAMPAIGN_MISSING`. On success `design_status` moves `DRAFT` → `DESIGN_FROZEN`, `design_frozen_at` is stamped with the logical clock, `frozen_revision_id` is recorded, the model's `version` increments, and `dhf_retention_until` with `retention_anchor_source` is computed for the first time per §2.10 — on a model with no lots, no closed incidents, and no recall, the anchor is `design_frozen_at` and the source is `DESIGN_FREEZE`. Freezing never touches `market_status`.

Releasing a model to the retail channel belongs to a `ComplianceOfficer` and moves `market_status` `NOT_RELEASED` → `RETAIL_RELEASED`, stamping `market_status_changed_at` with the logical clock and incrementing the model's `version`. Four gates guard it. The model's `market_status` must be `NOT_RELEASED`, or the request is rejected with `ERR_PRODUCT_STATE_INVALID`. Its `design_status` must be `DESIGN_FROZEN`, or the request is rejected with `ERR_DESIGN_NOT_FROZEN`. Every one of the six mandated document kinds — `DUTY_RATING_LABEL`, `WARNING_LABEL`, `INSTRUCTION_LABEL`, `RETAIL_CARTON`, `ASSEMBLY_INSTRUCTION_SHEET`, and `CONSUMER_SAFETY_SHEET` — must have at least one document for this model in `APPROVED`; a gap is rejected with `ERR_LABEL_SET_INCOMPLETE`. Note that `CERT_MARK_LABEL` is not among the mandated kinds, and that a document which has since moved to `SUPERSEDED` does not satisfy its kind. Finally, at least one listing record of the model must be in `LISTED`, or the release is rejected with `ERR_NO_ACTIVE_LISTING`.

Stopping shipment is available to a `ComplianceOfficer` or a `SafetyDirector` on a model in `RETAIL_RELEASED`, with a `reason_code` of `LOT_QUARANTINE`, `FIELD_INCIDENT_REVIEW`, or `LISTING_SUSPENDED`; a model that is not `RETAIL_RELEASED` is rejected with `ERR_PRODUCT_STATE_INVALID`. The transition `RETAIL_RELEASED` → `STOP_SHIP` sets `stop_ship_reason_code` from the supplied `reason_code`, stamps `market_status_changed_at` with the logical clock, and cascades: every listing record of the model in `LISTED` moves `LISTED` → `SUSPENDED` with `suspension_reason` set to `STOP_SHIP_CASCADE` and `audit_due_at` cleared, every test campaign of the model in `PLANNED` moves to `CANCELLED`, and every one of those campaigns' `HELD` reservations moves to `CANCELLED` with its `duration_minutes` subtracted from its bench's `reserved_minutes_total`. The same transition is reached without an operator when a lot of the model is quarantined, in which case the reason recorded is `LOT_QUARANTINE`, and when a `LISTED` listing of the model becomes `SUSPENDED`, in which case it is `LISTING_SUSPENDED`. Because the transition is guarded to fire only from `RETAIL_RELEASED`, the listing-suspension cascade cannot re-enter it and loop.

Resuming shipment is reserved to a `SafetyDirector` and closes the cycle back `STOP_SHIP` → `RETAIL_RELEASED`. Three preconditions apply beyond the model being in `STOP_SHIP`, which is otherwise rejected with `ERR_PRODUCT_STATE_INVALID`. The model's `risk_score_mitigated` must be strictly below 25.00, or the resume is rejected with `ERR_RISK_SCORE_ABOVE_THRESHOLD` — note that the threshold is compared against the mitigated variant only, never the gross one. No lot of the model may still be in `QUARANTINED`, and the model's `held_registration_count` must be exactly 0; either condition failing is rejected with `ERR_QUARANTINE_HOLD_PRESENT`. On success `stop_ship_reason_code` is cleared to null, `market_status_changed_at` is stamped with the logical clock, and every listing record of the model in `SUSPENDED` moves `SUSPENDED` → `LISTED` with `suspended_at` and `suspension_reason` cleared to null and `audit_due_at` re-stamped at the logical clock advanced by that record's owning body's `audit_interval_days`. Test campaigns cancelled during the stop-ship are not resurrected; new ones must be planned. The same `STOP_SHIP` → `RETAIL_RELEASED` transition, with the same cascade, also fires as a system event when a corrective-action verification drops `risk_score_mitigated` below the clearing threshold; in that system-triggered form, any precondition that fails simply causes the resume arm to be skipped, and the verification request still succeeds.

### 3.8. Consumer Registration, Field Incidents and Design Corrective Action

Consumer registration is what makes lot traceability reach a doorstep. A `Consumer`, or a `ComplianceOfficer` acting on a consumer's behalf, registers a unit by naming the `production_lot_id` it was built in, a `consumer_email` for recall notification, a `purchase_channel` of `BIG_BOX_RETAIL`, `PRO_DEALER`, or `ONLINE`, the `purchase_date`, and the `serial_suffix` stamped on the rail. The named lot must have `status` `RELEASED` or `QUARANTINED`, since a consumer cannot own a unit that never shipped; a lot still `OPEN` or `IN_PROCESS`, or already `SCRAPPED`, is rejected with `ERR_LOT_NOT_SHIPPABLE`. A `purchase_date` later than the logical clock is rejected with `ERR_DATE_IN_FUTURE`. A new registration begins at `registration_status` `REGISTERED` with `hold_flag` false, `recall_event_id` null, and `notified_at`, `acknowledged_at`, and `remedy_choice` all null — except that when the referenced lot is already `QUARANTINED`, `hold_flag` is set to true at once and the model's `held_registration_count` is recomputed immediately.

A **field incident** may be filed by a `ComplianceOfficer`, a `SafetyDirector`, or the `Consumer` who experienced it. The payload names the `product_id` involved, the `incident_type` — one of `RAIL_FRACTURE`, `RUNG_SEPARATION`, `HINGE_FAILURE`, `SLIP_FALL`, or `LABEL_ILLEGIBLE` — the worst `injury_severity` reported, which is one of `NONE`, `MINOR`, `HOSPITALIZATION`, or `FATALITY`, the `occurred_at` instant, and a free-text `narrative`. Two optional links improve traceability: `production_lot_id` for the lot involved when it is traceable, and `consumer_registration_id` for the reporting consumer's registration when it is known. An `occurred_at` later than the logical clock is rejected with `ERR_DATE_IN_FUTURE`. A filed incident begins at `status` `REPORTED` with `requires_capa` false, `incident_points` null, and `finding`, `root_cause_code`, and `closed_at` all null. A `REPORTED` incident contributes nothing to either risk-score variant.

Opening an investigation moves the incident `REPORTED` → `UNDER_INVESTIGATION`, increments the incident's `version`, derives that incident's `incident_points`, and recomputes both of the model's risk scores — this is the moment the incident enters both variants for the first time. `incident_points` is the product of a severity weight and a type weight, rounded half up to two decimal places. The severity weights are 1 for `NONE`, 4 for `MINOR`, 12 for `HOSPITALIZATION`, and 30 for `FATALITY`. The type weights are 3.0 for `RAIL_FRACTURE`, 2.5 for `RUNG_SEPARATION`, 2.0 for `HINGE_FAILURE`, 1.5 for `SLIP_FALL`, and 1.0 for `LABEL_ILLEGIBLE`.

**The two risk variants.** Both read exactly the same input set: the model's field incidents whose `status` is `UNDER_INVESTIGATION`, `ROOT_CAUSE_IDENTIFIED`, `CAPA_OPENED`, or `CLOSED`. Incidents in `REPORTED` or `NOT_SUBSTANTIATED` are excluded from both. `risk_score_gross` is the un-discounted exposure used for the liability dossier and regulatory disclosure: every incident in the set contributes its full `incident_points` regardless of corrective-action state. `risk_score_mitigated` is the figure the resume-ship gate reads: an incident that has at least one corrective action in `VERIFIED` contributes only one quarter of its `incident_points`, while every other in-set incident contributes its full points; a corrective action in `SUPERSEDED` never grants that credit. In both variants the sum is first clamped to a ceiling of 100.00 and only then rounded half up to two decimal places — the ceiling is applied to the sum before the final rounding. For identical incident data the mitigated variant is therefore strictly lower than the gross one once any corrective action has been verified.

Resolving the investigation is a `SafetyDirector` decision that **forks**, and the two branches carry deliberately different side-effect sets. The director supplies a `finding` of either `NOT_SUBSTANTIATED` or `ROOT_CAUSE_IDENTIFIED`, with an optional `root_cause_code` drawn from `RIVET_SHEAR_MARGIN`, `RAIL_SECTION_MODULUS`, `LABEL_ADHESION`, `HINGE_STOP_GEOMETRY`, or `CONSUMER_MISUSE`. The pairing rule is strict in both directions: `ROOT_CAUSE_IDENTIFIED` requires a non-null `root_cause_code`, and `NOT_SUBSTANTIATED` requires `root_cause_code` to be null; either mismatch is rejected with `ERR_FINDING_ROOT_CAUSE_MISMATCH`.

On the `NOT_SUBSTANTIATED` branch, `status` moves `UNDER_INVESTIGATION` → `NOT_SUBSTANTIATED`, `finding` is set to `NOT_SUBSTANTIATED`, `closed_at` is stamped with the logical clock, `requires_capa` stays false, `root_cause_code` stays null, and both risk scores are recomputed **with this incident removed from both input sets**. `NOT_SUBSTANTIATED` is terminal and opens no corrective-action obligation. Because the retention computation of §2.10 only reads incidents whose `status` is `CLOSED`, a `NOT_SUBSTANTIATED` incident never anchors design-history retention despite carrying a `closed_at`.

On the `ROOT_CAUSE_IDENTIFIED` branch, `status` moves `UNDER_INVESTIGATION` → `ROOT_CAUSE_IDENTIFIED`, `finding` is set to `ROOT_CAUSE_IDENTIFIED`, the supplied `root_cause_code` is stored, `requires_capa` is set to true, and `closed_at` stays null. On this branch the risk scores are **not** recomputed: the incident stays in both input sets at full weight. `ROOT_CAUSE_IDENTIFIED` is not terminal — it opens a corrective-action obligation. An investigation requested on an incident that is not `REPORTED`, a resolution requested on one that is not `UNDER_INVESTIGATION`, and a corrective action created against one that is not `ROOT_CAUSE_IDENTIFIED` are each rejected with `ERR_INCIDENT_STATE_INVALID`.

A **corrective action** is authored by a `DesignEngineer` or a `SafetyDirector` against an incident in `ROOT_CAUSE_IDENTIFIED` whose `requires_capa` is true. The payload names the `field_incident_id`, an `action_summary`, and the mandatory `expected_field_incident_version` of §2.8; optionally it names a `design_revision_id` when the fix is a design change (null for a process-only action) and a `supersedes_action_id` naming a prior action on the **same** incident that is still `OPEN` and that this one replaces. A `supersedes_action_id` pointing at an action on a different incident is rejected with `ERR_SUPERSEDE_TARGET_MISMATCH`. Creating the action sets its `status` to `OPEN`, stamps `authored_by_user_id` with the author's `X-User-ID`, leaves `verified_at` and `verified_by_user_id` null, moves the incident `ROOT_CAUSE_IDENTIFIED` → `CAPA_OPENED`, increments the incident's `version` by one, and moves any action named by `supersedes_action_id` from `OPEN` to the terminal `SUPERSEDED`. A superseded action can no longer be verified, and a verification requested on an action that is already `VERIFIED` or `SUPERSEDED` is rejected with `ERR_CORRECTIVE_ACTION_NOT_OPEN`.

Verification belongs to a `DesignApprover`, must not be performed by whoever authored the action — `X-User-ID` equal to `authored_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` — and, when the action names a `design_revision_id`, requires that revision to be `APPROVED`, otherwise `ERR_REVISION_NOT_APPROVED`. Verification then drives a **four-hop chain** whose trigger is entirely different from the quarantine chain but whose reach is comparable. **Hop one:** the action moves `OPEN` → `VERIFIED`, `verified_at` is stamped with the logical clock, and `verified_by_user_id` records the verifier's `X-User-ID`. **Hop two,** caused by hop one: because the action is now verified, its field incident moves `CAPA_OPENED` → `CLOSED` and the incident's `closed_at` is stamped with the logical clock; this is the join point of the investigation fork, at which both branches have reached a terminal status. **Hop three,** caused by hop two: because the incident closed, the model's `risk_score_mitigated` is recomputed with the one-quarter credit now applying to that incident, and `dhf_retention_until` with `retention_anchor_source` is re-derived from the new `closed_at`, taking `INCIDENT_CLOSURE` as the source when that instant is the latest candidate. **Hop four,** caused by hop three: if the recomputed `risk_score_mitigated` has dropped below 25.00 and the model is in `STOP_SHIP` with no lot in `QUARANTINED` and a `held_registration_count` of 0, the model moves `STOP_SHIP` → `RETAIL_RELEASED`, which in turn returns every `SUSPENDED` listing record of the model to `LISTED` with `audit_due_at` re-stamped as described in §3.7. When those conditions do not hold, hop four is skipped and the verification still succeeds.

### 3.9. Recall Readiness, Exposure Accounting and Closure

A `SafetyDirector` drafts a **recall event** naming the `product_id` being recalled, a `remedy_type` of `REPAIR_KIT`, `REPLACEMENT`, or `REFUND`, a non-empty `affected_revision_ids` array of the design revision identifiers inside the recall scope, and the `hazard_description` that will be published. Only one live recall per model is permitted: if any other recall event for that model is in `DRAFT`, `ANNOUNCED`, or `IN_PROGRESS`, the draft is rejected with `ERR_RECALL_ALREADY_OPEN`. A drafted recall begins at `status` `DRAFT` with every exposure figure null and `announced_at` and `closed_at` null.

Announcement is the irreversible step, and it freezes the numbers. The recall must be in `DRAFT`, or the request is rejected with `ERR_RECALL_STATE_INVALID`, and the model's `market_status` must be either `RETAIL_RELEASED` or `STOP_SHIP`. The recall's in-scope lot set must be non-empty, or the announcement is rejected with `ERR_RECALL_SCOPE_EMPTY`.

**The in-scope lot set** is shared by both exposure figures, so the two always read the same lots. It is every production lot whose `product_id` is the recalled model, whose pinned `design_revision_id` is a member of `affected_revision_ids`, whose `status` is `RELEASED` or `QUARANTINED`, and whose `released_at` is not null. Lots in `SCRAPPED`, `OPEN`, or `IN_PROCESS` are excluded from both figures.

**Two defensible counting bases give two different answers, and both are recorded.** `exposure_units_shipped_basis` is the units-in-commerce figure published with the regulatory notice: it is the sum of `produced_units` across every lot in the in-scope set, so it sees every unit that left the plant, including unregistered ones. `exposure_units_registered_basis` is the consumer-outreach figure that drives the remedy ledger: it is the count of consumer registrations whose `production_lot_id` is one of the in-scope lots and whose `registration_status` is `REGISTERED`, `NOTIFIED`, or `ACKNOWLEDGED`. Because it counts registrations rather than units, for the same lots it is normally far smaller than the shipped basis. `notification_coverage_pct` is the registered basis divided by the shipped basis expressed as a percentage, rounded half up to two decimal places; when the shipped basis is 0 the calculation short-circuits to 0.00 rather than dividing.

Announcement moves the recall `DRAFT` → `ANNOUNCED`, stamps `announced_at` with the logical clock, freezes both exposure figures and `notification_coverage_pct`, sets `units_remedied` to 0 and `units_outstanding` to the registered basis, and stamps `recall_event_id` on every in-scope consumer registration whose `registration_status` is `REGISTERED`. It then reshapes the model in both dimensions at once: `market_status` moves to the terminal `RECALLED` from whichever of `RETAIL_RELEASED` or `STOP_SHIP` it held, with `market_status_changed_at` stamped; `design_status` moves `DESIGN_FROZEN` → the terminal `DESIGN_OBSOLETE`; every listing record of the model in `LISTED` or `SUSPENDED` moves to the terminal `WITHDRAWN` with `audit_due_at` cleared to null, after which no further audit campaign may be planned against that record; and `dhf_retention_until` with `retention_anchor_source` is recomputed, taking `RECALL` as the source when the recall's `market_status_changed_at` is the latest candidate. When the model was in `STOP_SHIP` at announcement, its `stop_ship_reason_code` is retained rather than cleared, so the liability dossier keeps the reason shipment stopped.

Notification moves the recall `ANNOUNCED` → `IN_PROGRESS` and may be performed by a `SafetyDirector` or a `ComplianceOfficer`; a recall that is not `ANNOUNCED` is rejected with `ERR_RECALL_STATE_INVALID`. Every consumer registration stamped with this `recall_event_id` and still in `REGISTERED` moves `REGISTERED` → `NOTIFIED` with `notified_at` stamped at the logical clock.

Acknowledgement is the consumer's own act, available to a `Consumer` or a `ComplianceOfficer` on their behalf, and it takes a `remedy_choice` of `REPAIR_KIT`, `REPLACEMENT`, or `REFUND`. The registration must be in `NOTIFIED`; one still `REGISTERED` or already `ACKNOWLEDGED` is rejected with `ERR_REGISTRATION_NOT_NOTIFIED`. Since a registration only reaches `NOTIFIED` when its recall moves to `IN_PROGRESS`, the recall is necessarily under way at this point. The supplied `remedy_choice` must equal the recall's `remedy_type`, or the acknowledgement is rejected with `ERR_REMEDY_CHOICE_MISMATCH` — consumers take the remedy the recall offers, not one of their choosing. On success the registration moves `NOTIFIED` → the terminal `ACKNOWLEDGED`, `acknowledged_at` is stamped with the logical clock, `remedy_choice` is stored, the recall's `units_remedied` increases by one, and its `units_outstanding` decreases by one — so `units_remedied` plus `units_outstanding` always equals `exposure_units_registered_basis`.

Closing the recall moves it `IN_PROGRESS` → the terminal `CLOSED` and stamps `closed_at` with the logical clock; a recall that is not `IN_PROGRESS` is rejected with `ERR_RECALL_STATE_INVALID`. A recall may close on either of two grounds: every remedy is accounted for, meaning `units_outstanding` is exactly 0, or the outreach window has run out, meaning the logical clock has reached or passed `announced_at` advanced by 365 days — one 365-day year. When neither ground holds, the close is rejected with `ERR_RECALL_UNITS_OUTSTANDING`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — every state transition, every disposition, every approval — return `200 OK`, as do all read operations. All business paths are mounted under `/ladder-ops`; the logical-clock capability sits outside that mount.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ladder-ops/products` | Catalogue a new ladder model and derive its load requirements | DesignEngineer |
| GET | `/ladder-ops/products/{id}` | Read a single ladder model | DesignEngineer, DesignApprover, TestLabTechnician, ProductionSupervisor, ComplianceOfficer, CertificationBody, SafetyDirector |
| GET | `/ladder-ops/products` | List ladder models | DesignEngineer, DesignApprover, TestLabTechnician, ProductionSupervisor, ComplianceOfficer, CertificationBody, SafetyDirector |
| POST | `/ladder-ops/products/{id}/freeze-design` | Freeze the design against an approved revision | DesignApprover |
| POST | `/ladder-ops/products/{id}/release-to-retail` | Release the model to the retail channel | ComplianceOfficer |
| POST | `/ladder-ops/products/{id}/stop-ship` | Stop shipment of the model | ComplianceOfficer, SafetyDirector |
| POST | `/ladder-ops/products/{id}/resume-ship` | Resume shipment of a stopped model | SafetyDirector |
| GET | `/ladder-ops/products/{id}/documents` | List the model's label and packaging documents | DesignEngineer, DesignApprover, ComplianceOfficer, CertificationBody, SafetyDirector |
| GET | `/ladder-ops/products/{id}/liability-dossier` | Read the consolidated product-liability dossier | ComplianceOfficer, SafetyDirector |
| POST | `/ladder-ops/design-revisions` | Create a design revision for a model | DesignEngineer |
| GET | `/ladder-ops/design-revisions/{id}` | Read a single design revision | DesignEngineer, DesignApprover, TestLabTechnician, ProductionSupervisor, ComplianceOfficer, SafetyDirector |
| GET | `/ladder-ops/design-revisions` | List design revisions | DesignEngineer, DesignApprover, TestLabTechnician, ProductionSupervisor, ComplianceOfficer, SafetyDirector |
| POST | `/ladder-ops/design-revisions/{id}/submit` | Submit a draft revision for review | DesignEngineer |
| POST | `/ladder-ops/design-revisions/{id}/review` | Approve a revision or request changes | DesignApprover |
| POST | `/ladder-ops/design-revisions/{id}/revise` | Return a changes-requested revision to draft | DesignEngineer |
| POST | `/ladder-ops/product-documents` | Draft a label or packaging document | DesignEngineer, ComplianceOfficer |
| POST | `/ladder-ops/product-documents/{id}/approve` | Approve a drafted document | ComplianceOfficer |
| POST | `/ladder-ops/test-benches` | Register a load-test bench | TestLabTechnician |
| GET | `/ladder-ops/test-benches/{id}` | Read a single test bench | TestLabTechnician, ComplianceOfficer, SafetyDirector |
| POST | `/ladder-ops/bench-reservations` | Reserve a bench interval for a campaign | TestLabTechnician |
| GET | `/ladder-ops/bench-reservations/{id}` | Read a single bench reservation | TestLabTechnician, ComplianceOfficer, SafetyDirector |
| GET | `/ladder-ops/bench-reservations` | List bench reservations | TestLabTechnician, ComplianceOfficer, SafetyDirector |
| POST | `/ladder-ops/bench-reservations/{id}/cancel` | Cancel a held bench reservation | TestLabTechnician |
| POST | `/ladder-ops/test-campaigns` | Plan a test campaign | TestLabTechnician, ComplianceOfficer |
| GET | `/ladder-ops/test-campaigns/{id}` | Read a single test campaign | TestLabTechnician, DesignEngineer, DesignApprover, ComplianceOfficer, CertificationBody, SafetyDirector |
| GET | `/ladder-ops/test-campaigns` | List test campaigns | TestLabTechnician, DesignEngineer, DesignApprover, ComplianceOfficer, CertificationBody, SafetyDirector |
| POST | `/ladder-ops/test-campaigns/{id}/start` | Start a planned campaign on a held reservation | TestLabTechnician |
| POST | `/ladder-ops/test-campaigns/{id}/load-tests` | Record a load test and derive its verdict | TestLabTechnician |
| GET | `/ladder-ops/test-campaigns/{id}/load-tests` | List a campaign's load tests | TestLabTechnician, DesignEngineer, DesignApprover, ComplianceOfficer, CertificationBody, SafetyDirector |
| POST | `/ladder-ops/test-campaigns/{id}/conclude` | Conclude a campaign as passed or failed | TestLabTechnician |
| POST | `/ladder-ops/production-lots` | Open a production lot pinned to a revision | ProductionSupervisor |
| GET | `/ladder-ops/production-lots/{id}` | Read a single production lot | ProductionSupervisor, TestLabTechnician, ComplianceOfficer, CertificationBody, SafetyDirector |
| GET | `/ladder-ops/production-lots` | List production lots | ProductionSupervisor, TestLabTechnician, ComplianceOfficer, CertificationBody, SafetyDirector |
| POST | `/ladder-ops/production-lots/{id}/start-production` | Start production and record the units built | ProductionSupervisor |
| POST | `/ladder-ops/production-lots/{id}/joint-samples` | Record a rivet/joint pull sample | TestLabTechnician, ProductionSupervisor |
| GET | `/ladder-ops/production-lots/{id}/joint-samples` | List a lot's joint integrity samples | TestLabTechnician, ProductionSupervisor, ComplianceOfficer, CertificationBody, SafetyDirector |
| POST | `/ladder-ops/production-lots/{id}/release` | Release a lot to the retail channel | ProductionSupervisor |
| POST | `/ladder-ops/production-lots/{id}/quarantine` | Quarantine a lot | ProductionSupervisor, ComplianceOfficer, SafetyDirector |
| POST | `/ladder-ops/production-lots/{id}/disposition` | Dispose of a quarantined lot by release or scrap | ProductionSupervisor, SafetyDirector |
| POST | `/ladder-ops/listing-bodies` | Register a third-party certification body | ComplianceOfficer |
| POST | `/ladder-ops/listing-records` | File a listing application for a model | ComplianceOfficer |
| GET | `/ladder-ops/listing-records/{id}` | Read a single listing record | ComplianceOfficer, CertificationBody, DesignApprover, SafetyDirector |
| GET | `/ladder-ops/listing-records` | List listing records | ComplianceOfficer, CertificationBody, DesignApprover, SafetyDirector |
| POST | `/ladder-ops/listing-records/{id}/list` | Grant the listing | CertificationBody |
| POST | `/ladder-ops/listing-records/{id}/suspend` | Suspend a listing | CertificationBody |
| POST | `/ladder-ops/consumer-registrations` | Register a purchased unit | Consumer, ComplianceOfficer |
| GET | `/ladder-ops/consumer-registrations/{id}` | Read a single consumer registration | Consumer, ComplianceOfficer, SafetyDirector |
| GET | `/ladder-ops/consumer-registrations` | List consumer registrations | ComplianceOfficer, SafetyDirector |
| POST | `/ladder-ops/consumer-registrations/{id}/acknowledge` | Acknowledge a recall notice and choose a remedy | Consumer, ComplianceOfficer |
| POST | `/ladder-ops/field-incidents` | Report a field incident | ComplianceOfficer, SafetyDirector, Consumer |
| GET | `/ladder-ops/field-incidents/{id}` | Read a single field incident | ComplianceOfficer, SafetyDirector, DesignEngineer, DesignApprover |
| GET | `/ladder-ops/field-incidents` | List field incidents | ComplianceOfficer, SafetyDirector, DesignEngineer, DesignApprover |
| POST | `/ladder-ops/field-incidents/{id}/investigate` | Open an investigation and score the incident | SafetyDirector, ComplianceOfficer |
| POST | `/ladder-ops/field-incidents/{id}/resolve-investigation` | Record the investigation finding | SafetyDirector |
| POST | `/ladder-ops/corrective-actions` | Open a design corrective action on an incident | DesignEngineer, SafetyDirector |
| GET | `/ladder-ops/corrective-actions/{id}` | Read a single corrective action | DesignEngineer, DesignApprover, SafetyDirector, ComplianceOfficer |
| GET | `/ladder-ops/corrective-actions` | List corrective actions | DesignEngineer, DesignApprover, SafetyDirector, ComplianceOfficer |
| POST | `/ladder-ops/corrective-actions/{id}/verify` | Verify a corrective action and close its incident | DesignApprover |
| POST | `/ladder-ops/recall-events` | Draft a recall event | SafetyDirector |
| GET | `/ladder-ops/recall-events/{id}` | Read a single recall event | SafetyDirector, ComplianceOfficer, Consumer |
| GET | `/ladder-ops/recall-events` | List recall events | SafetyDirector, ComplianceOfficer |
| POST | `/ladder-ops/recall-events/{id}/announce` | Announce the recall and freeze exposure | SafetyDirector |
| POST | `/ladder-ops/recall-events/{id}/notify` | Notify in-scope consumer registrations | SafetyDirector, ComplianceOfficer |
| POST | `/ladder-ops/recall-events/{id}/close` | Close the recall | SafetyDirector |
| POST | `/_clock/set_current_utc` | Set the deterministic logical clock | SystemOperator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_LISTING_BODY_MISMATCH` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_SCRAP_REQUIRES_SAFETY_DIRECTOR` | 403 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_DESIGN_REVISION_NOT_FOUND` | 404 |
| `ERR_PRODUCT_DOCUMENT_NOT_FOUND` | 404 |
| `ERR_TEST_BENCH_NOT_FOUND` | 404 |
| `ERR_BENCH_RESERVATION_NOT_FOUND` | 404 |
| `ERR_TEST_CAMPAIGN_NOT_FOUND` | 404 |
| `ERR_PRODUCTION_LOT_NOT_FOUND` | 404 |
| `ERR_LISTING_BODY_NOT_FOUND` | 404 |
| `ERR_LISTING_RECORD_NOT_FOUND` | 404 |
| `ERR_CONSUMER_REGISTRATION_NOT_FOUND` | 404 |
| `ERR_FIELD_INCIDENT_NOT_FOUND` | 404 |
| `ERR_CORRECTIVE_ACTION_NOT_FOUND` | 404 |
| `ERR_RECALL_EVENT_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_PAGINATION` | 400 |
| `ERR_INVALID_WINDOW` | 400 |
| `ERR_DATE_IN_FUTURE` | 400 |
| `ERR_STALE_PRODUCT_VERSION` | 412 |
| `ERR_STALE_INCIDENT_VERSION` | 412 |
| `ERR_REVISION_STATE_INVALID` | 409 |
| `ERR_DOCUMENT_NOT_DRAFT` | 409 |
| `ERR_CAMPAIGN_STATE_INVALID` | 409 |
| `ERR_RESERVATION_NOT_HELD` | 409 |
| `ERR_LOT_STATE_INVALID` | 409 |
| `ERR_LISTING_STATE_INVALID` | 409 |
| `ERR_PRODUCT_STATE_INVALID` | 409 |
| `ERR_INCIDENT_STATE_INVALID` | 409 |
| `ERR_CORRECTIVE_ACTION_NOT_OPEN` | 409 |
| `ERR_RECALL_STATE_INVALID` | 409 |
| `ERR_REGISTRATION_NOT_NOTIFIED` | 409 |
| `ERR_NO_JOINT_SAMPLES` | 422 |
| `ERR_JOINT_SAMPLE_COUNT_SHORT` | 422 |
| `ERR_JOINT_INTEGRITY_FAILURE` | 422 |
| `ERR_CONFORMANCE_BELOW_MINIMUM` | 422 |
| `ERR_LABEL_SET_INCOMPLETE` | 422 |
| `ERR_LABEL_PLACEMENT_INVALID` | 422 |
| `ERR_REVISION_PRODUCT_MISMATCH` | 409 |
| `ERR_AUDIT_SCOPE_MISMATCH` | 409 |
| `ERR_AUDIT_FIELDS_MISMATCH` | 422 |
| `ERR_SUPERSEDE_TARGET_MISMATCH` | 409 |
| `ERR_REVISION_NOT_APPROVED` | 409 |
| `ERR_DESIGN_NOT_FROZEN` | 409 |
| `ERR_QUALIFYING_CAMPAIGN_MISSING` | 422 |
| `ERR_STANDARD_NOT_ACCREDITED` | 422 |
| `ERR_NO_ACTIVE_LISTING` | 422 |
| `ERR_BENCH_CAPACITY_INSUFFICIENT` | 422 |
| `ERR_PROCESS_TRACEABILITY_MISSING` | 422 |
| `ERR_PRODUCED_UNITS_INVALID` | 422 |
| `ERR_LOT_NOT_SHIPPABLE` | 409 |
| `ERR_REQUIRED_TESTS_MISSING` | 422 |
| `ERR_AUDIT_SAMPLE_SHORT` | 422 |
| `ERR_RISK_SCORE_ABOVE_THRESHOLD` | 422 |
| `ERR_QUARANTINE_HOLD_PRESENT` | 409 |
| `ERR_RECALL_ALREADY_OPEN` | 409 |
| `ERR_RECALL_SCOPE_EMPTY` | 422 |
| `ERR_RECALL_UNITS_OUTSTANDING` | 409 |
| `ERR_REMEDY_CHOICE_MISMATCH` | 422 |
| `ERR_FINDING_ROOT_CAUSE_MISMATCH` | 422 |
| `ERR_DESIGN_MARGIN_INSUFFICIENT` | 422 |
| `ERR_BENCH_WINDOW_CONFLICT` | 409 |
| `ERR_AUDIT_WINDOW_OVERLAP` | 409 |
| `ERR_DUPLICATE_KEY` | 409 |

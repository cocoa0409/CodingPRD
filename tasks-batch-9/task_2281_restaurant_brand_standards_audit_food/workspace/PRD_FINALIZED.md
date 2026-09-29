# Restaurant Brand Standards Audit API — Product Requirements Document

## 1. Introduction

Multi-unit restaurant brands live or die on the consistency of their operating standards, and the people who verify that consistency are third-party field auditors who walk into a store — sometimes with notice, more often without — and score it line by line against a published rubric. The commercial reality behind this product is uncomfortable: a scored item is not merely an observation, it is the first link in a chain that can end in a notice of default or a recommendation to terminate a franchise agreement. Franchisees therefore contest scores, auditors drift from one another in how strictly they score, and health departments publish their own numbers that the brand cannot ignore. A brand standards program that cannot defend its arithmetic cannot defend its consequences.

This API is the system of record for that program. It owns the audit calendar and enforces the announced/unannounced visit mix that keeps unannounced coverage honest; it owns the rubric and its versioning, so that a visit scored in March is always scored against the rubric that was in force in March; it owns the scoring arithmetic, including the weighting of sections, the penalty ladder for critical food-safety violations, and the admission of health-department inspection results into a composite score; it owns the corrective-action loop, with photo evidence and severity-driven deadlines; it owns the dispute and appeal path, adjudicated by a calibration reviewer who is barred from reviewing their own work; it owns auditor calibration through shadow audits and a reliability score that can suspend a drifting auditor mid-engagement; and it owns the append-only escalation ledger from which every franchise-agreement consequence is derived and, when a visit is voided, compensated back out.

Two design commitments run through every section that follows. First, **derivation over assertion**: standing scores, risk indices, escalation levels, and agreement statuses are never set by a client — they are recomputed from primary records whenever a triggering event occurs, and the order in which they recompute is specified, not incidental. Second, **reversibility**: because a scored item can be amended on appeal and an entire visit can be voided after finalization, every consequence the system emits must have a defined compensating entry. The remainder of this document specifies the global contract (§2), the business narrative from which implementers reconstruct behaviour (§3), the HTTP surface (§4), and the error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which that principal acts. A request missing either header, or presenting a role string that is not one of the five declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A syntactically valid request whose acting role is not among the roles authorized for the target operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The five declared roles are `BrandAdmin`, `Auditor`, `CalibrationReviewer`, `Franchisee`, and `ComplianceIntegrator`.

- **`BrandAdmin`** is the brand compliance office. It owns the registry (brands, franchisees, locations, auditors), the rubric, calendar construction, finalization, voids, cure decisions, and the overdue sweep. When `X-User-Role` is `BrandAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but never compares it to any entity's `id`, and no ownership check is applied to a `BrandAdmin` request.
- **`Auditor`** is the field auditor who performs and scores visits and verifies remediation evidence. When `X-User-Role` is `Auditor`, `X-User-ID` is the `id` of the acting `Auditor` record; ownership checks on any resource that references an `Auditor` compare the resource's auditor foreign key to `X-User-ID` — concretely, a visit's `auditor_id` must equal `X-User-ID` for that auditor to start it, score items on it, submit it, or rescore it.
- **`CalibrationReviewer`** is a senior auditor sitting in the review seat: it records shadow-audit calibration and adjudicates scored-item appeals. When `X-User-Role` is `CalibrationReviewer`, `X-User-ID` is likewise the `id` of the acting `Auditor` record — the same backing entity as the `Auditor` role, in a different capacity. Segregation of duties bars this principal from acting on a dispute raised against a visit that the same auditor scored.
- **`Franchisee`** operates one or more locations, cures corrective actions with photo evidence, and appeals scored items. When `X-User-Role` is `Franchisee`, `X-User-ID` is the `id` of the acting `Franchisee` record; ownership checks compare the resource's franchisee foreign key to `X-User-ID` — a corrective action's `assigned_franchisee_id`, a dispute's `filed_by_franchisee_id`, or a location's `franchisee_id`.
- **`ComplianceIntegrator`** is the health-department data integration operator and is the only role that may import or disregard inspection results. When `X-User-Role` is `ComplianceIntegrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

For the three entity-backed roles — `Auditor`, `CalibrationReviewer`, and `Franchisee` — the identifier in `X-User-ID` must resolve to an existing row of the backing entity. If it does not, the request fails with `ERR_ACTING_IDENTITY_NOT_FOUND` (HTTP 404), which is evaluated before any ownership comparison. When the acting principal resolves but does not own the target resource, the rejection is `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When a `CalibrationReviewer` would be reviewing their own scoring, or when a shadow visit would be assigned to the same auditor who performed the visit being shadowed, the rejection is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

Collection endpoints are paginated through two query parameters. `limit` caps the number of records returned; it defaults to 10 when omitted, may not be smaller than 1, and may not exceed 100. `offset` is the number of records to skip and defaults to 0; it may not be negative. A `limit` outside the range of 1 through 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a specific collection states otherwise, list results are ordered by `created_at` ascending.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of records matching the filter before pagination is applied and `has_more` indicates whether records remain beyond the current page.

### 2.4. The Logical Clock

Every temporal rule in this system — visit notice windows, start windows, corrective-action deadlines, health-inspection lookbacks, repeat-violation lookbacks, reliability windows — evaluates against a server-held **logical clock**, never against wall-clock time. Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time under any circumstance. A `BrandAdmin` may advance or rewind it by supplying `to_iso8601`, and the response reports the resulting instant as `current_utc`. Every system-stamped instant in this document — `started_at`, `submitted_at`, `finalized_at`, `filed_at`, `resolved_at`, `submitted_at` on a corrective action, `verified_at`, `escalated_at`, `published_at`, `certification_period_start`, `cure_period_started_at`, `recorded_at`, and `occurred_at` — is the value of the logical clock at the moment the operation was accepted.

Client-supplied instants that describe the past are validated against the same clock: neither `captured_at` on a photo nor `inspection_date` on a health inspection may lie after the current logical clock, and a violation of either is rejected with `ERR_TIMESTAMP_IN_FUTURE` (HTTP 422).

### 2.5. Common Resource Properties

Brands, franchisees, auditors, locations, rubric versions, audit visits, scored items, corrective actions, disputes, and health inspections are all fully versioned resources and carry the following server-managed fields:

- **`id`** (string): a server-minted UUID. No type prefix is used; the identifier is a bare UUID.
- **`created_at`** (string): the ISO 8601 UTC instant, with three fractional digits, at which the record was first created.
- **`updated_at`** (string): the ISO 8601 UTC instant, with three fractional digits, of the most recent mutation of the record.
- **`version`** (integer): a monotonically increasing counter that advances by one on every mutation of the record.

Recomputation of a derived field counts as a mutation. When a visit finalize recomputes a location's `standing_score`, the location's `updated_at` is refreshed and its `version` advances; the same holds for a brand whose `brand_risk_index` is recomputed, and for a franchisee whose default counters move.

Three record types are deliberately lighter. `RubricItem`, `EvidencePhoto`, `CalibrationRecord`, and `EscalationEvent` records carry only `id` and `created_at`: both `updated_at` and `version` are absent from these four, because a rubric line item, a photo, a calibration measurement, and a ledger entry are each written once and never revised.

### 2.6. Scoring Precision and Rounding Discipline

All percentages, composite scores, penalty amounts, standing scores, reliability scores, variance measurements, and risk-index values are decimal numbers carried to exactly **two decimal places**, and every rounding step uses **round half up**. Where a calculation specifies more than one rounding step — the section-percent computation rounds once per rubric item and once again per section — each step is a separate round-half-up to two decimals, and the intermediate rounded values, not the unrounded ones, feed the next step. Where a calculation specifies that intermediates are carried at full precision (the renormalized recency weights of the location standing score), they are carried at full precision and rounded exactly once at the stated point.

Counts — `critical_violation_count`, `repeat_violation_count`, `item_count`, `critical_item_count`, `location_count`, `default_location_count`, `open_default_location_count`, `open_corrective_action_count`, `submission_count`, `rejection_count`, `evidence_photo_count`, `info_request_count`, `rescore_count`, `finalized_visit_count`, and `escalation_level` — are integers. Threshold comparisons throughout the system are inclusive at the boundary unless the text explicitly says "strictly": a composite score of exactly 90.00 earns `PASS`, a reliability score of exactly 70.00 clears certification, a variance of exactly 2.00 points lands in the `EXCELLENT` band, and an unannounced ratio exactly equal to the brand minimum passes.

### 2.7. Derivation Cascades: Visit to Location to Franchisee to Brand

No client ever writes a derived value. Instead, a small number of primary events — submitting a visit, rescoring a visit, finalizing a visit, voiding a visit, resolving a dispute as an amendment, verifying a corrective action, escalating an overdue critical corrective action, and accepting a cure — trigger a cascade that always runs outward in the same direction: the visit's own numbers first, then the location's, then the franchisee's counters, then the brand's aggregates.

Concretely, a recompute at visit level covers the three section percents (`food_safety_percent`, `brand_standards_percent`, `facility_percent`), `critical_violation_count`, `critical_penalty_points`, `composite_score` with its `composite_variant`, and `grade`. A recompute at location level covers `standing_score`, `latest_grade`, `repeat_violation_count`, and — whenever a ledger entry was appended — `escalation_level` and `franchise_agreement_status`. A recompute at franchisee level covers `open_default_location_count` and `termination_recommended`. A recompute at brand level covers `default_location_count` and `brand_risk_index` with its derived `brand_risk_tier`. `Brand.location_count` is not part of this cascade; it moves only when a location is registered.

Because these cascades are immediate and synchronous, a read taken after any triggering write already reflects the complete cascade. There is no eventual-consistency window and no deferred job.

### 2.8. Nested Path Resolution and Ordered Validation

Path identifiers are resolved strictly left to right, and the first identifier that does not resolve determines the 404 that is returned: `ERR_BRAND_NOT_FOUND`, `ERR_FRANCHISEE_NOT_FOUND`, `ERR_AUDITOR_NOT_FOUND`, `ERR_LOCATION_NOT_FOUND`, `ERR_RUBRIC_VERSION_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_SCORED_ITEM_NOT_FOUND`, `ERR_CORRECTIVE_ACTION_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, or `ERR_HEALTH_INSPECTION_NOT_FOUND`. Foreign keys carried in a request body are resolved after the path and before any business rule, and produce the corresponding 404 for the entity that is missing — including `ERR_RUBRIC_ITEM_NOT_FOUND` for a `rubric_item_id` that does not exist.

Where several checks could fire on the same request, the system evaluates them in a fixed precedence so that the reported error is deterministic. In order:

1. Header presence and role validity — `ERR_UNAUTHENTICATED`, on every endpoint.
2. Role authorization for the endpoint — `ERR_UNAUTHORIZED`, on every endpoint.
3. Existence of every path identifier, left to right — the matching not-found error, on every endpoint that has path parameters.
4. Resolution of `X-User-ID` against the backing entity for entity-backed roles — `ERR_ACTING_IDENTITY_NOT_FOUND`, on every endpoint whose authorized roles include `Auditor`, `CalibrationReviewer`, or `Franchisee`.
5. Ownership of the target resource by the acting principal — `ERR_NOT_RESOURCE_OWNER`, on `POST /audit-visits/{id}/start`, `POST /audit-visits/{id}/submit`, `POST /audit-visits/{id}/rescore`, `POST /audit-visits/{id}/scored-items`, `POST /corrective-actions/{id}/submit`, `POST /disputes`, `POST /disputes/{id}/supplement`, `POST /disputes/{id}/withdraw`, and `POST /evidence-photos`.
6. Request-body well-formedness — required fields present, types correct, enum values in range, integers inside their declared bounds, `limit` between 1 and 100 and `offset` at least 0 — `ERR_INVALID_REQUEST`, on every endpoint.
7. Existence of every foreign key in the request body — the matching not-found error, on every write endpoint that carries foreign keys.
8. The target resource is in a state from which the requested transition is legal — `ERR_INVALID_VISIT_STATE`, `ERR_INVALID_CORRECTIVE_ACTION_STATE`, `ERR_INVALID_DISPUTE_STATE`, `ERR_INVALID_RUBRIC_STATE`, `ERR_INVALID_AUDITOR_STATE`, or `ERR_NO_ESCALATION_TO_CURE` as appropriate — on every action endpoint.
9. A new visit's rubric version is `PUBLISHED` — `ERR_RUBRIC_VERSION_NOT_PUBLISHED`, on `POST /audit-visits`.
10. `expected_brand_version` matches the brand's current `version` — `ERR_STALE_BRAND_VERSION`, on `POST /rubric-versions`.
11. `expected_visit_version` matches the visit's current `version` — `ERR_STALE_VISIT_VERSION`, on `POST /audit-visits/{id}/rescore`.
12. The auditor bound to the operation is not `SUSPENDED` — `ERR_AUDITOR_SUSPENDED`, on `POST /audit-visits`, `POST /audit-visits/{id}/start`, `POST /corrective-actions/{id}/verify`, `POST /disputes/{id}/request-info`, `POST /disputes/{id}/resolve`, and `POST /calibration-records`.
13. The auditor bound to the operation is `CERTIFIED`, so that a `PROVISIONAL` auditor may neither score, verify, nor review — `ERR_AUDITOR_NOT_CERTIFIED`, on `POST /audit-visits/{id}/start`, `POST /corrective-actions/{id}/verify`, `POST /disputes/{id}/request-info`, and `POST /disputes/{id}/resolve`.
14. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES`, on `POST /disputes/{id}/request-info`, `POST /disputes/{id}/resolve`, `POST /audit-visits`, and `POST /calibration-records`.
15. No scored item of the visit is `UNDER_DISPUTE` — `ERR_UNRESOLVED_DISPUTE`, on `POST /audit-visits/{id}/finalize`, `POST /audit-visits/{id}/rescore`, and `POST /audit-visits/{id}/void`.
16. A location's franchisee belongs to the location's brand — `ERR_FRANCHISEE_BRAND_MISMATCH` (HTTP 422), on `POST /locations`.
17. A scored item's rubric item belongs to the visit's pinned rubric version — `ERR_RUBRIC_ITEM_NOT_IN_VISIT_RUBRIC` (HTTP 422), on `POST /audit-visits/{id}/scored-items`.
18. `shadow_of_visit_id` is present exactly when `visit_type` is `SHADOW` — `ERR_SHADOW_LINK_MISMATCH` (HTTP 422), on `POST /audit-visits`.
19. The shadow target is a non-shadow, non-voided visit at the same location on the same rubric version — `ERR_SHADOW_TARGET_INVALID` (HTTP 422), on `POST /audit-visits`.
20. An evidence photo names exactly one of `corrective_action_id` and `dispute_id` — `ERR_EVIDENCE_TARGET_AMBIGUOUS` (HTTP 422), on `POST /evidence-photos`.
21. Calibration inputs are complete — `ERR_CALIBRATION_INPUTS_INCOMPLETE` (HTTP 422), on `POST /calibration-records`.
22. `scheduled_end_at` is strictly after `scheduled_start_at` — `ERR_INVALID_VISIT_WINDOW` (HTTP 422), on `POST /audit-visits`.
23. An announced visit carries sufficient notice — `ERR_ANNOUNCED_NOTICE_TOO_SHORT` (HTTP 422), on `POST /audit-visits`.
24. The rubric version is already effective for the scheduled date — `ERR_RUBRIC_NOT_EFFECTIVE` (HTTP 422), on `POST /audit-visits`.
25. Client-supplied past instants are not in the future — `ERR_TIMESTAMP_IN_FUTURE` (HTTP 422), on `POST /evidence-photos` and `POST /health-inspections`.
26. The auditor is not otherwise occupied — `ERR_AUDITOR_SCHEDULE_CONFLICT` (HTTP 409), on `POST /audit-visits`.
27. The location's unannounced-visit density quota is respected — `ERR_LOCATION_VISIT_WINDOW_QUOTA` (HTTP 409), on `POST /audit-visits`.
28. The visit's start window is open — `ERR_VISIT_WINDOW_NOT_OPEN` (HTTP 409), on `POST /audit-visits/{id}/start`.
29. The resulting unannounced mix clears the brand minimum — `ERR_UNANNOUNCED_MIX_BELOW_MINIMUM` (HTTP 422), on `POST /audit-visits`.
30. `points_awarded` lies between 0 and the rubric item's `max_points` inclusive — `ERR_POINTS_EXCEED_MAX` (HTTP 422), on `POST /audit-visits/{id}/scored-items` and `POST /audit-visits/{id}/rescore`.
31. The rubric item is not already scored on this visit — `ERR_ITEM_ALREADY_SCORED` (HTTP 409), on `POST /audit-visits/{id}/scored-items`.
32. Every critical rubric item has been scored — `ERR_CRITICAL_ITEMS_UNSCORED` (HTTP 422), on `POST /audit-visits/{id}/submit`.
33. `rescore_count` is below 2 — `ERR_RESCORE_LIMIT_REACHED` (HTTP 409), on `POST /audit-visits/{id}/rescore`.
34. The rubric's item points sum to its declared total — `ERR_RUBRIC_TOTAL_MISMATCH` (HTTP 422), on `POST /rubric-versions/{id}/publish`.
35. The rubric holds a critical item and covers all three sections — `ERR_RUBRIC_SECTION_INCOMPLETE` (HTTP 422), on `POST /rubric-versions/{id}/publish`.
36. Requested and granted appeal points are strictly above the scored item's current `points_awarded` and at most the rubric item's `max_points` — `ERR_DISPUTE_POINTS_INVALID` (HTTP 422), on `POST /disputes` and `POST /disputes/{id}/resolve`.
37. No other unresolved dispute exists on the scored item — `ERR_DISPUTE_ALREADY_OPEN` (HTTP 409), on `POST /disputes`.
38. `info_request_count` is below 2 — `ERR_INFO_REQUEST_LIMIT_REACHED` (HTTP 409), on `POST /disputes/{id}/request-info`.
39. At least one evidence photo is attached — `ERR_EVIDENCE_REQUIRED` (HTTP 422), on `POST /corrective-actions/{id}/submit` and `POST /disputes/{id}/supplement`.
40. A critical corrective action that already escalated may not be cured late — `ERR_LATE_CURE_NOT_ALLOWED` (HTTP 409), on `POST /corrective-actions/{id}/submit`.
41. Cure acceptance requires no open corrective actions — `ERR_OPEN_CORRECTIVE_ACTIONS` (HTTP 409), on `POST /locations/{id}/cure-acceptance`.
42. Certification requires a sufficient certification-review reliability score — `ERR_RELIABILITY_BELOW_FLOOR` (HTTP 409), on `POST /auditors/{id}/certify`.
43. A finalized visit whose corrective action was already verified may not be voided — `ERR_VERIFIED_ACTION_BLOCKS_VOID` (HTTP 409), on `POST /audit-visits/{id}/void`.
44. Only one calibration record may exist per shadow visit — `ERR_CALIBRATION_ALREADY_RECORDED` (HTTP 409), on `POST /calibration-records`.
45. `brand_code`, `employee_code`, and `store_number` within a brand are unique — `ERR_DUPLICATE_RESOURCE_CODE` (HTTP 409), on `POST /brands`, `POST /auditors`, and `POST /locations`.
46. `version_label` is unique within a brand, and `item_code` and `display_order` are unique within a rubric version — `ERR_DUPLICATE_RUBRIC_ENTRY` (HTTP 409), on `POST /rubric-versions` and `POST /rubric-versions/{id}/rubric-items`.

This ordering is normative. A request that violates a lower-numbered rule and a higher-numbered rule at once reports the lower-numbered error.

### 2.9. Optimistic Concurrency on Brand and Visit Writes

Two write operations are guarded by optimistic concurrency control, and only those two.

Drafting a rubric version (`POST /rubric-versions`) requires a non-optional `expected_brand_version` field carrying the client's last observed `version` of the target `Brand`. If that value does not equal the brand's current `version`, the request is rejected with `ERR_STALE_BRAND_VERSION` and HTTP 412. The reason is substantive rather than cosmetic: a new rubric version may legitimately supersede and retire the brand's current one, so a writer holding an out-of-date view of the brand must re-read it before drafting. A successful draft itself advances `Brand.version` by one, so a client that drafts two rubric versions in sequence must re-read the brand between them.

Rescoring a submitted visit (`POST /audit-visits/{id}/rescore`) requires a non-optional `expected_visit_version` field carrying the client's last observed `version` of the target `AuditVisit`. If that value does not equal the visit's current `version`, the request is rejected with `ERR_STALE_VISIT_VERSION` and HTTP 412. A rescore overwrites the points on a scored item outright, so a writer whose view of the visit predates an earlier accepted rescore must re-read the visit first. Each accepted rescore advances `AuditVisit.version` by one.

No other endpoint accepts a version field, and no other endpoint performs a version check. Where a version field is absent from an endpoint's input, supplying one has no defined effect.

### 2.10. Auditor Standing and Segregation of Duties

Auditor standing is a system-wide gate rather than a per-endpoint detail. An auditor whose `status` is `SUSPENDED` may not be bound to visit creation, visit start, corrective-action verification, dispute information requests, dispute resolution, or calibration recording; every one of those six operations rejects with `ERR_AUDITOR_SUSPENDED`. An auditor whose `status` is `PROVISIONAL` may be scheduled onto a calendar but may not act: visit start, corrective-action verification, dispute information requests, and dispute resolution all reject with `ERR_AUDITOR_NOT_CERTIFIED`. Only `CERTIFIED` auditors score, verify, and review.

Segregation of duties has two independent expressions. On the appeal path, the acting `CalibrationReviewer` must not be the auditor who scored the visit that the disputed item belongs to. On the calibration path, a shadow visit may not be assigned to the same auditor who performed the visit it shadows. Both violations report `ERR_SEGREGATION_OF_DUTIES`.

### 2.11. The Escalation Ledger as the Single Source of Franchise Consequences

A location's `escalation_level` and its `franchise_agreement_status` are never assigned directly. They are projections of an append-only ledger of `EscalationEvent` records, and that ledger is never pruned. Each entry records the `location_id` it belongs to, optionally the `corrective_action_id` or the `audit_visit_id` that originated it, an `event_type`, a `level_delta`, the `resulting_escalation_level` and `resulting_agreement_status` immediately after the entry was applied, and the `occurred_at` instant.

Four entry kinds exist. `REPEAT_CRITICAL` and `OVERDUE_CRITICAL` each carry a `level_delta` of positive one. `CURE_ACCEPTED` and `VOID_REVERSAL` each carry a `level_delta` of negative one. To project the level, the ledger is read in `occurred_at` ascending order with `created_at` ascending as the tiebreaker, the deltas are summed, and the result is floored at zero, so `escalation_level` is never negative. The status then follows directly from the level: level zero is `GOOD_STANDING`, level one is `NOTICE_OF_DEFAULT`, level two is `CURE_PERIOD`, and level three or higher is `TERMINATION_RECOMMENDED`. Every append re-runs this projection.

## 3. Business Logic & Workflows

### 3.1. Establishing the Brand, Its Franchisees, and Its Locations

A brand standards program begins when the compliance office registers a **Brand** with its trade `name` (1 to 120 characters, required) and a `brand_code` — a short identifier of 2 to 8 uppercase alphanumeric characters that appears on audit paperwork and must be globally unique. The registration may also set `unannounced_min_ratio_pct`, the minimum share of a location's rolling audit calendar that must consist of unannounced visits, expressed as an integer percentage from 0 through 100; when the caller omits it, the brand adopts 40. A freshly registered brand starts with `brand_risk_index` at 0.00, `brand_risk_tier` at `BASELINE`, `location_count` at 0, and `default_location_count` at 0.

Each **Franchisee** is registered under exactly one brand, identified in the payload by `brand_id`, and carries a `legal_name` of 1 to 160 characters, a `contact_email` that must contain an at-sign and serves as the corrective-action notification address, and `agreement_signed_at`, the instant the franchise agreement was executed. A franchisee's two derived fields — `open_default_location_count`, the number of its locations whose `franchise_agreement_status` is anything other than `GOOD_STANDING`, and `termination_recommended`, which becomes true as soon as any one of its locations reaches `TERMINATION_RECOMMENDED` — both begin at their empty values (zero and false) and move only through the cascades described in §2.7.

A **Location** is a single restaurant. Its payload names the `brand_id`, the `franchisee_id` of the operator, a `store_number` of 3 to 16 characters that must be unique within its brand, and a `region_code` drawn from `NORTHEAST`, `SOUTHEAST`, `MIDWEST`, and `WEST` for trend reporting. Registration enforces a referential rule that is easy to get wrong: the named franchisee must itself belong to the same brand as the location, and a cross-brand pairing is rejected with `ERR_FRANCHISEE_BRAND_MISMATCH`. A duplicate `brand_code`, `employee_code`, or `store_number` within its brand is rejected with `ERR_DUPLICATE_RESOURCE_CODE`. Each accepted location raises its brand's `location_count` by one.

Locations start out unrated and in good standing: `standing_score` is 0.00, `latest_grade` is null, `open_corrective_action_count` is 0, `repeat_violation_count` is 0, `escalation_level` is 0, `franchise_agreement_status` is `GOOD_STANDING`, and `cure_period_started_at` is null. For cross-location trend reporting, the location collection can be narrowed by `brand_id`, `franchisee_id`, `region_code`, and `franchise_agreement_status`; the franchisee collection can be narrowed by `brand_id`.

### 3.2. Authoring and Publishing a Scoring Rubric

Scoring is only meaningful against a frozen rubric, so a **RubricVersion** is drafted, populated, and only then published. Drafting names the owning `brand_id`, a `version_label` such as RV-2026.1 that must be unique within the brand, an `effective_from` instant that is the earliest planned visit start the rubric may govern, and a declared `total_points` between 1 and 1000. A draft may optionally name `supersedes_rubric_version_id`, a self-reference to the rubric version it is intended to replace. The draft is created with `status` `DRAFT`, `published_at` null, `item_count` 0, and `critical_item_count` 0, and — as §2.9 sets out — the request must carry `expected_brand_version`. Each accepted draft advances the brand's `version` by one. A duplicate `version_label` inside the brand is rejected with `ERR_DUPLICATE_RUBRIC_ENTRY`.

Line items are appended to a draft one at a time. A **RubricItem** belongs to a `rubric_version_id` and carries an `item_code` unique within that rubric version, a `section` of `FOOD_SAFETY`, `BRAND_STANDARDS`, or `FACILITY`, a `max_points` value between 1 and 100, an `is_critical` flag that defaults to false and marks the item as a critical food-safety control, and a `display_order` between 1 and 999 that must also be unique within the rubric version and gives items a deterministic sequence inside their section. Duplicate `item_code` or `display_order` values inside one rubric version are likewise rejected with `ERR_DUPLICATE_RUBRIC_ENTRY`. Each append raises the rubric version's `item_count` by one, raises `critical_item_count` by one when the new item is critical, and advances the rubric version's `version` by one. Items may only be appended while the rubric version is `DRAFT`; an attempt against a published or retired version is rejected with `ERR_INVALID_RUBRIC_STATE`. The line items of a rubric version can be read back in `display_order`, optionally narrowed to one `section`.

Publication is the `DRAFT → PUBLISHED` transition and is reserved to the compliance office. Four preconditions apply. The rubric must hold at least one item, and at least one of those items must be critical; the sum of the `max_points` of all attached items must equal the declared `total_points`; and each of `FOOD_SAFETY`, `BRAND_STANDARDS`, and `FACILITY` must contain at least one item. A points mismatch reports `ERR_RUBRIC_TOTAL_MISMATCH`, while a missing critical item or an empty section reports `ERR_RUBRIC_SECTION_INCOMPLETE`. Publication stamps `published_at` with the logical clock. If the newly published version names a `supersedes_rubric_version_id` and that predecessor is currently `PUBLISHED`, the predecessor is driven `PUBLISHED → RETIRED` in the same operation.

Retirement is deliberately non-destructive. Audit visits already scheduled against a retired rubric version keep their pinned `rubric_version_id` and continue to be scored against it, item for item; what retirement forbids is *new* visits referencing that version. Rubric versions can be listed and filtered by `brand_id`, by `status`, and by `supersedes_rubric_version_id` — the last of these is how an operator finds the successor chain of a given version.

### 3.3. Building the Audit Calendar

Calendar construction is a compliance-office activity, and it is the single most heavily validated write in the system. Scheduling an **AuditVisit** names the `location_id`, the `auditor_id` who will score it, the `rubric_version_id` the visit will be pinned to, a `visit_type` of `ANNOUNCED`, `UNANNOUNCED`, or `SHADOW`, and the planned window as `scheduled_start_at` (inclusive) and `scheduled_end_at` (exclusive). A shadow visit additionally names `shadow_of_visit_id`. The visit is created with `status` `SCHEDULED`; `started_at`, `submitted_at`, `finalized_at`, all three section percents, `health_component_percent`, `composite_score`, `composite_variant`, `grade`, `linked_health_inspection_id`, and `void_reason` are all null at creation, while `critical_violation_count`, `critical_penalty_points`, and `rescore_count` begin at 0, 0.00, and 0 respectively.

The pinned rubric must be `PUBLISHED` at the moment the visit is created — a draft or retired version is rejected with `ERR_RUBRIC_VERSION_NOT_PUBLISHED` — and its `effective_from` must fall at or before the visit's `scheduled_start_at`, otherwise the request is rejected with `ERR_RUBRIC_NOT_EFFECTIVE`. The window itself must be non-degenerate: `scheduled_end_at` strictly after `scheduled_start_at`, or `ERR_INVALID_VISIT_WINDOW`. The auditor bound to the visit must not be suspended, or the request fails with `ERR_AUDITOR_SUSPENDED`; a `PROVISIONAL` auditor may, however, be placed on the calendar, because certification is enforced when the visit starts rather than when it is booked.

**Notice.** For an `ANNOUNCED` visit the system records `announced_notice_hours`, the number of hours between the logical clock at creation time and `scheduled_start_at`, rounded half up to two decimal places. That rounded figure is both the value stored on the visit and the value the notice check compares, and it must be at least 72.00 — three full days of notice — and a shorter lead time is rejected with `ERR_ANNOUNCED_NOTICE_TOO_SHORT`. For `UNANNOUNCED` and `SHADOW` visits `announced_notice_hours` stays null, since neither carries a notice obligation.

**Shadow linkage.** `shadow_of_visit_id` must be present exactly when `visit_type` is `SHADOW` and absent otherwise; either mismatch is rejected with `ERR_SHADOW_LINK_MISMATCH`. The named target must be a non-shadow visit at the same location, pinned to the same `rubric_version_id`, and not itself voided; a target that fails any of those tests is rejected with `ERR_SHADOW_TARGET_INVALID`. As §2.10 states, the shadow visit's auditor may not be the auditor of the target visit, which reports `ERR_SEGREGATION_OF_DUTIES`.

**Auditor occupation.** An auditor cannot be in two restaurants at once, and needs travel time between them. The candidate visit occupies the half-open interval that begins at its `scheduled_start_at` and ends just before its `scheduled_end_at`. Every existing non-voided visit of the same auditor is expanded by a 60-minute travel buffer at both ends, and if the candidate interval intersects any expanded interval the request is rejected with `ERR_AUDITOR_SCHEDULE_CONFLICT`. Because the candidate interval is half-open, a visit that begins exactly when the buffered predecessor interval ends does not conflict.

**Location density quota.** Independently of the auditor, a single restaurant may not be swarmed with surprise visits. Consider the closed window that extends seven days on either side of the candidate's `scheduled_start_at`, a fourteen-day span centred on the candidate. Counting the candidate itself, at most two non-voided `UNANNOUNCED` visits may have a `scheduled_start_at` inside that window; a third is rejected with `ERR_LOCATION_VISIT_WINDOW_QUOTA`.

**The unannounced mix.** The brand's `unannounced_min_ratio_pct` is enforced at the moment a visit is created, against a rolling calendar centred on the candidate. Take the candidate's `scheduled_start_at` as the pivot and build the window that reaches back 182 days and forward 182 days from that pivot, inclusive on both ends — a 364-day span centred on the candidate. Collect every visit of the candidate's location whose `visit_type` is either `ANNOUNCED` or `UNANNOUNCED`, whose `status` is one of `SCHEDULED`, `IN_PROGRESS`, `SUBMITTED`, or `FINALIZED`, and whose `scheduled_start_at` falls inside that window. The denominator is the number of visits so collected plus one for the candidate; the numerator is the number of collected visits whose `visit_type` is `UNANNOUNCED`, plus one more when the candidate itself is unannounced. Divide the numerator by the denominator, multiply by 100, and round half up to two decimal places. If that percentage is below the brand's `unannounced_min_ratio_pct`, creation is rejected with `ERR_UNANNOUNCED_MIX_BELOW_MINIMUM`; a percentage exactly equal to the minimum passes. Shadow visits and voided visits never appear on either side of this fraction — a shadow audit is a supervision exercise, not calendar coverage.

The visit collection is the calendar view and can be filtered by `location_id`, `auditor_id`, `rubric_version_id`, `shadow_of_visit_id`, `linked_health_inspection_id`, `status`, and `visit_type`. That last pair of filters is also how an operator locates the shadow visits awaiting calibration and the visits attached to a particular imported inspection.

### 3.4. Conducting the Visit: Scoring, Submission, and Rescoring

An auditor opens a visit by starting it, which advances `SCHEDULED → IN_PROGRESS` and stamps `started_at` with the logical clock. Four conditions must hold. The acting auditor must be the visit's own `auditor_id`, or the request fails with `ERR_NOT_RESOURCE_OWNER`. That auditor's `status` must be `CERTIFIED`: a `SUSPENDED` auditor is stopped with `ERR_AUDITOR_SUSPENDED` and a `PROVISIONAL` one with `ERR_AUDITOR_NOT_CERTIFIED`. The start window must be open — the logical clock must be at or after `scheduled_start_at` minus 60 minutes, so an auditor may open the visit up to an hour early but no earlier, and a premature attempt is rejected with `ERR_VISIT_WINDOW_NOT_OPEN`. Finally, the visit's pinned rubric version must be either `PUBLISHED` or `RETIRED`; retirement in the interval between scheduling and arrival never blocks the auditor.

While the visit is `IN_PROGRESS`, its auditor records one **ScoredItem** per rubric line item observed. Each scoring call names the `rubric_item_id` and the `points_awarded`, and may carry a free-text `note` of up to 500 characters holding the auditor's observation. The named rubric item must belong to the visit's pinned rubric version, or the call is rejected with `ERR_RUBRIC_ITEM_NOT_IN_VISIT_RUBRIC`; `points_awarded` must be at least 0 and at most that rubric item's `max_points`, or the call is rejected with `ERR_POINTS_EXCEED_MAX`; and the same rubric item may not be scored twice on one visit, which reports `ERR_ITEM_ALREADY_SCORED`. Each scored item records its parent `visit_id`, sets `original_points_awarded` and `effective_points_awarded` equal to the submitted `points_awarded`, leaves `amended_points_awarded` null, and enters `status` `SCORED`. Two derived flags follow immediately: `is_violation` is true exactly when `effective_points_awarded` is strictly less than the rubric item's `max_points`, and `severity` is `CRITICAL` when the rubric item is critical and the item is a violation, `STANDARD` when it is a violation on a non-critical item, and `NONE` when it is not a violation at all. `original_points_awarded` is written once and never changes thereafter, which is what makes an auditor's first judgement auditable after any number of corrections. Scored items can be listed and filtered by `visit_id`, `rubric_item_id`, `status`, and `severity`.

Submission advances `IN_PROGRESS → SUBMITTED`, and again the acting auditor must be the visit's own auditor. One substantive precondition applies: every rubric item of the pinned rubric version marked critical must already have a scored item on this visit, and a gap is rejected with `ERR_CRITICAL_ITEMS_UNSCORED`. Non-critical items may be left unscored; the arithmetic treats them as having earned zero of their maximum points, which is a deliberate incentive to score the whole rubric. Submission stamps `submitted_at` and runs the full scoring pipeline described below, computing the composite under the `PROVISIONAL` variant, setting `composite_variant` to `PROVISIONAL`, and deriving the `grade`. No health-department figure participates in a provisional composite.

**Section percents.** For each of `FOOD_SAFETY`, `BRAND_STANDARDS`, and `FACILITY` in turn, take every rubric item of the visit's pinned rubric version belonging to that section, in ascending `display_order`. For each such item, take the `effective_points_awarded` of its scored item, or zero when the item has no scored item. Divide that awarded figure by the item's `max_points`, multiply by 100, and round half up to two decimal places — **this per-item rounding happens first**. Then sum those rounded per-item percentages, divide by the number of rubric items in the section, and round half up to two decimal places again; the result is `food_safety_percent`, `brand_standards_percent`, or `facility_percent` respectively. The section percent is therefore the mean of the individually rounded per-item percentages, *not* the ratio of the section's total awarded points to its total maximum points; the two formulations produce different numbers and, through the composite, can produce a different grade. A voided visit computes none of these.

**Rubric percent.** The three section percents are then combined by weight: food safety at one half, brand standards at three tenths, and facility at one fifth. Multiply each section percent by its weight, add the three products, and round half up to two decimal places. The result is the visit's rubric percent — an intermediate figure, not a stored field.

**Critical penalty.** Count the scored items of the visit whose `severity` is `CRITICAL`; that count is `critical_violation_count`. The penalty ladder is stepped, not linear: `critical_penalty_points` is 0.00 when there are no critical violations, 5.00 when there is exactly one, 12.00 when there are exactly two, and 25.00 when there are three or more. Subtract `critical_penalty_points` from the rubric percent, round half up to two decimal places, and take the greater of that figure and 0.00 — a visit's base score never goes negative no matter how many critical failures it accumulates. This base score is the second intermediate figure feeding the composite.

**Provisional composite and grade.** Under the `PROVISIONAL` variant, `composite_score` is the base score multiplied by six tenths plus `food_safety_percent` multiplied by four tenths, rounded half up to two decimal places — food safety is thus double-counted by design, once inside the base score and once alongside it. Immediately after any composite is computed, the `grade` is derived. If `critical_violation_count` is 2 or more, the grade is `FAIL` regardless of the score; this override outranks the score bands entirely. Otherwise a `composite_score` of at least 90.00 grades `PASS`, a score of at least 80.00 grades `CONDITIONAL`, and anything lower grades `FAIL`.

**Rescoring.** An auditor who realises a mistake after submission may correct exactly one scored item per call while the visit remains `SUBMITTED`; this is a self-loop that leaves the visit in `SUBMITTED`. The call names the `scored_item_id`, the corrected `points_awarded`, and `expected_visit_version` per §2.9. The acting auditor must own the visit; the corrected points must still respect the item's `max_points`, or `ERR_POINTS_EXCEED_MAX` fires; `rescore_count` must be strictly below 2, so at most two rescores are ever accepted on one visit and a third reports `ERR_RESCORE_LIMIT_REACHED`; and no scored item of the visit may be `UNDER_DISPUTE`, which reports `ERR_UNRESOLVED_DISPUTE`. An accepted rescore overwrites `points_awarded` on the named scored item while leaving `original_points_awarded` untouched, raises `rescore_count` by one, re-runs the section percents, `critical_violation_count`, `critical_penalty_points`, the `PROVISIONAL` composite and the `grade`, and advances the visit's `version` by one.

### 3.5. Admitting Health-Department Results and Finalizing the Visit

Health-department data enters the system through a separate, narrow channel. A `ComplianceIntegrator` imports a **HealthInspection** naming the `location_id`, the `authority_name` that performed it (1 to 120 characters), the `inspection_date`, the `points_scored`, the `points_possible` on that authority's scale (between 1 and 1000, with `points_scored` at least 0 and at most `points_possible`), and the posted `letter_grade`, one of `A`, `B`, `C`, or `FAIL`. The `inspection_date` may not lie after the logical clock, or the import is rejected with `ERR_TIMESTAMP_IN_FUTURE`. An imported inspection enters with `status` `RECORDED`, which makes it eligible for composite selection, and `disregard_reason` null. When a record turns out to be unusable, the same integrator may disregard it, which sets `status` to `DISREGARDED`, removes it permanently from the eligibility pool, and records a `disregard_reason` of `SUPERSEDED_BY_REINSPECTION`, `WRONG_LOCATION`, or `DATA_ERROR`. A location's inspections can be read back and narrowed by `status`.

Finalization is the compliance office's act, advancing `SUBMITTED → FINALIZED`, and it is the moment the visit stops being an auditor's working document and becomes a consequence-bearing record. Two preconditions apply: no scored item of the visit may be `UNDER_DISPUTE`, which reports `ERR_UNRESOLVED_DISPUTE`; and if the visit is a shadow visit, the visit named by its `shadow_of_visit_id` must itself already be `FINALIZED`, otherwise the request is rejected with `ERR_INVALID_VISIT_STATE`. Finalization stamps `finalized_at` with the logical clock and then performs, in order, the health selection, the final composite, the corrective-action assignment, and the outward cascade.

**Selecting the health component.** Take the visit's `scheduled_start_at` as the window end. An inspection is eligible when it belongs to the visit's location, its `status` is `RECORDED`, its `inspection_date` is at or before that window end, and its `inspection_date` is no earlier than 180 days before that window end. Disregarded inspections are excluded outright. If no inspection is eligible, `linked_health_inspection_id` and `health_component_percent` both stay null. Otherwise, order the eligible inspections by `inspection_date` descending, breaking ties by `created_at` descending, and take the first; its `id` is stored as `linked_health_inspection_id`. Its raw percentage is `points_scored` divided by `points_possible`, multiplied by 100, rounded half up to two decimal places. A posted letter grade then imposes a ceiling: `A` and `B` cap the contribution at 100.00, so they are effectively uncapped; `C` caps it at 79.00; and `FAIL` caps it at 0.00. `health_component_percent` is the lesser of the raw percentage and that cap — a restaurant cannot buy back a failed health inspection with a generous point score.

**The final composite.** The `FINAL` variant admits the health figure and dilutes the rubric: `composite_score` becomes the base score multiplied by forty-five hundredths, plus `food_safety_percent` multiplied by three tenths, plus `health_component_percent` multiplied by twenty-five hundredths, rounded half up to two decimal places. `composite_variant` is set to `FINAL`. Because the weights differ from the provisional set, an identical set of scored items yields a different composite at finalization than it did at submission, and can therefore yield a different `grade`. When no eligible inspection was found and `health_component_percent` is null, the final composite falls back to the provisional weight set — base score at six tenths plus `food_safety_percent` at four tenths — but `composite_variant` is still recorded as `FINAL`. The `grade` is re-derived from the new composite under the same rules, critical-violation override included.

**Assigning corrective actions.** Finalization creates exactly one **CorrectiveAction** per violating scored item — that is, per scored item whose `is_violation` is true. Each action records the originating `scored_item_id`, copies the `location_id` from the scored item's visit and the `assigned_franchisee_id` from that location at the moment of assignment, and copies the scored item's `severity`, which is either `STANDARD` or `CRITICAL`. Severity drives the deadline: `due_at` is 72 hours after the visit's `finalized_at` for a `CRITICAL` action and 14 days after `finalized_at` for a `STANDARD` one, expressed to whole seconds in ISO 8601 UTC. Each new action enters `status` `ASSIGNED` with `submission_count`, `rejection_count`, and `evidence_photo_count` at zero and `submitted_at`, `verified_at`, and `escalated_at` null. The location's `open_corrective_action_count` rises by the number of actions created.

**The outward cascade.** Finalization then raises the scoring auditor's `finalized_visit_count` by one and recomputes the location. `Location.standing_score` and `latest_grade` are recomputed as described in §3.9, as is `repeat_violation_count`. Repeat-violation accounting works on rubric-item identity within a trailing window: take the window that begins 365 days before the current logical clock, collect the location's `FINALIZED` visits whose `finalized_at` falls at or after that boundary, and for each `rubric_item_id` count the distinct visits among them that hold a scored item on that rubric item with `severity` `CRITICAL`. `repeat_violation_count` is the number of rubric items for which that count reaches 2 or more. Matching is by `rubric_item_id`, not by `item_code` — the same item code carried forward into a superseding rubric version is a *different* item and therefore does not repeat against its predecessor. For each rubric item that this very visit pushed to its second critical violation inside the 365-day window, finalization appends one `REPEAT_CRITICAL` ledger entry naming this visit as `audit_visit_id`, and each such entry raises the location's `escalation_level` and re-derives `franchise_agreement_status` per §2.11. Finally, the location's movement propagates to `Franchisee.open_default_location_count`, `Franchisee.termination_recommended`, `Brand.default_location_count`, and `Brand.brand_risk_index`.

### 3.6. Curing Violations: The Corrective-Action Loop

Every violation surfaced by a finalized visit becomes the franchisee's problem, tracked as a corrective action whose lifecycle is a loop rather than a line. Corrective actions can be listed and filtered by `scored_item_id`, `location_id`, `assigned_franchisee_id`, `status`, and `severity`.

Remediation is evidenced by photographs. An **EvidencePhoto** is attached by either a `Franchisee` or an `Auditor` and names exactly one of `corrective_action_id` and `dispute_id`; naming both, or naming neither, is rejected with `ERR_EVIDENCE_TARGET_AMBIGUOUS`. The photo carries a `file_uri` storage locator that must begin with `s3://`, a `captured_at` instant that may not lie after the logical clock (`ERR_TIMESTAMP_IN_FUTURE` otherwise), and an optional `caption` of up to 200 characters. The server records `uploaded_by_role` from the acting role, which is therefore either `Franchisee` or `Auditor`. When the photo names a corrective action, that action's `evidence_photo_count` rises by one. The photos attached to a corrective action, and those attached to a dispute, can each be read back oldest first.

The franchisee assigned to an action submits it for verification, advancing `ASSIGNED → SUBMITTED` and optionally supplying a `remediation_note`. The acting franchisee must be the action's `assigned_franchisee_id`, or `ERR_NOT_RESOURCE_OWNER` fires, and `evidence_photo_count` must be at least 1, or the submission is rejected with `ERR_EVIDENCE_REQUIRED`. Each accepted submission raises `submission_count` by one and stamps `submitted_at` with the logical clock.

A certified auditor then verifies the submission by supplying an `outcome`. When the `outcome` is `ACCEPTED`, the action advances `SUBMITTED → VERIFIED`, `verified_at` is stamped, the location's `open_corrective_action_count` drops by one, and the brand's `brand_risk_index` is recomputed. When the `outcome` is `REJECTED`, a `rejection_reason` must accompany it, the action moves `SUBMITTED → REJECTED`, and `rejection_count` rises by one; the open-action count does not move, because the violation remains open. A rejected action may be resubmitted, advancing `REJECTED → SUBMITTED` under exactly the same ownership and evidence preconditions and again raising `submission_count` and refreshing `submitted_at`; this is the loop that lets a franchisee iterate on inadequate evidence. Verification is barred to suspended auditors (`ERR_AUDITOR_SUSPENDED`) and to provisional ones (`ERR_AUDITOR_NOT_CERTIFIED`).

Deadlines are enforced by an administrative sweep rather than by a timer. The sweep examines every corrective action in `ASSIGNED` or `REJECTED` whose `due_at` lies strictly before the current logical clock and moves each of them `ASSIGNED → OVERDUE` or `REJECTED → OVERDUE` respectively. It reports four figures: `swept_count` for the actions it examined and moved, `overdue_count` for those that landed in `OVERDUE`, `escalated_count` for those that continued on to `ESCALATED`, and `escalated_location_count` for the number of distinct locations affected by an escalation. The first three figures overlap rather than partition the sweep: every action the sweep moves lands in `OVERDUE` first, including one that immediately continues to `ESCALATED`, so `overdue_count` always equals `swept_count`, and `escalated_count` counts a subset of those same actions.

What happens after `OVERDUE` depends entirely on severity, and the asymmetry is the point. A `STANDARD` action sits in `OVERDUE` and may still be cured late: its franchisee can advance it `OVERDUE → SUBMITTED` with fresh evidence, subject to the same ownership and at-least-one-photo requirements, raising `submission_count` and refreshing `submitted_at`. A `CRITICAL` action never rests in `OVERDUE`: the moment it is swept there it immediately continues `OVERDUE → ESCALATED` as a system cascade. Escalation stamps `escalated_at`, lowers the location's `open_corrective_action_count` by one — an escalated action has left the open remediation pool and joined the franchise-agreement track — and appends an `OVERDUE_CRITICAL` ledger entry naming the action as `corrective_action_id`, which raises the location's `escalation_level` and re-derives `franchise_agreement_status`. That location movement then recomputes `Franchisee.open_default_location_count`, `Franchisee.termination_recommended`, `Brand.default_location_count`, and `Brand.brand_risk_index`. Because a critical action leaves `OVERDUE` in the same operation that put it there, a late submission against it is rejected with `ERR_LATE_CURE_NOT_ALLOWED`. A submission attempted from any other state — from `VERIFIED`, from `ESCALATED` for reasons other than late cure, or from `VOIDED` — is rejected with `ERR_INVALID_CORRECTIVE_ACTION_STATE`, as is a verification attempted against an action that is not `SUBMITTED`.

Corrective actions can also be withdrawn from play by upstream reversals. An action in `ASSIGNED` is driven `ASSIGNED → VOIDED` as a system cascade when its originating scored item is amended out of violation or when its originating visit is voided, and that void lowers the location's `open_corrective_action_count` by one. An action that already reached `ESCALATED` is driven `ESCALATED → VOIDED` under the same two triggers, and because its escalation had already been ledgered, the void appends a `VOID_REVERSAL` entry that lowers the location's `escalation_level` and re-derives `franchise_agreement_status`. `VERIFIED` and `VOIDED` are terminal. The escalation ledger entries originating from a single corrective action can be read back on their own.

### 3.7. Appeals: Disputing a Scored Line Item

A franchisee who believes a line item was scored unfairly files a **Dispute** against it, but only once the visit has been finalized — a working document is the auditor's to correct, while a finalized record is contestable. Filing names the `scored_item_id`, the `requested_points` the franchisee argues the item deserves, and a `reason` narrative of 10 to 1000 characters. The acting franchisee must own the location behind the scored item, or `ERR_NOT_RESOURCE_OWNER` fires. `requested_points` must exceed the scored item's current `points_awarded` and must not exceed the rubric item's `max_points`; a value outside that range is rejected with `ERR_DISPUTE_POINTS_INVALID`. Only one live dispute may exist per scored item: if another dispute on the same item is in `FILED`, `INFO_REQUESTED`, or `EVIDENCE_REVIEW`, the filing is rejected with `ERR_DISPUTE_ALREADY_OPEN`. If the parent visit is not `FINALIZED`, the filing is rejected with `ERR_INVALID_VISIT_STATE`.

An accepted filing sets `filed_by_franchisee_id` from the acting franchisee, stamps `filed_at` with the logical clock, leaves `reviewer_auditor_id` null while the dispute is unclaimed, sets `info_request_count` to 0, leaves `resolution_points` and `resolved_at` null, and enters `status` `FILED`. In the same operation, the scored item moves `SCORED → UNDER_DISPUTE`, and that single fact freezes a great deal: while any scored item of a visit is `UNDER_DISPUTE`, that visit can be neither finalized, nor rescored, nor voided.

From `FILED`, two paths open. A `CalibrationReviewer` may request additional information, advancing `FILED → INFO_REQUESTED` and supplying the `information_requested` text; this raises `info_request_count` by one and claims the dispute by setting `reviewer_auditor_id` to the acting auditor when that field is still null. The reviewer must be certified and must not be the auditor who scored the disputed visit. Alternatively, the filing franchisee may supplement the dispute with evidence, advancing `FILED → EVIDENCE_REVIEW`; supplementation accepts an optional `note` and requires that at least one evidence photo already reference this dispute, failing with `ERR_EVIDENCE_REQUIRED` otherwise. The same supplement action advances `INFO_REQUESTED → EVIDENCE_REVIEW` under the same preconditions.

Review may cycle. From `EVIDENCE_REVIEW` a reviewer may push the dispute back to `INFO_REQUESTED` for another round, again raising `info_request_count`; but `info_request_count` must be strictly below 2 for any information request to be accepted, so the `EVIDENCE_REVIEW → INFO_REQUESTED → EVIDENCE_REVIEW` cycle is capped at two rounds and a third request is rejected with `ERR_INFO_REQUEST_LIMIT_REACHED`. Any action attempted against a dispute whose current state does not permit it — a supplement against a resolved dispute, a resolution against a dispute still in `FILED` — is rejected with `ERR_INVALID_DISPUTE_STATE`.

Resolution happens only from `EVIDENCE_REVIEW`, is performed by a `CalibrationReviewer` who did not score the disputed visit, and carries an `outcome`, a mandatory `rationale`, and — when the outcome amends the score — `granted_points`. Both outcomes stamp `resolved_at` and set `resolution_points`.

When the `outcome` upholds the original score, the dispute moves `EVIDENCE_REVIEW → UPHELD`, `resolution_points` is set to the scored item's existing `points_awarded`, and the scored item moves `UNDER_DISPUTE → UPHELD`. Nothing numeric changes: `points_awarded` stands, the visit composite stands, and every location field stands.

When the `outcome` amends the score, `granted_points` must be strictly above the scored item's `points_awarded` and at most the rubric item's `max_points` — the same range that governs `requested_points`, enforced with the same `ERR_DISPUTE_POINTS_INVALID` — and must differ from the current `points_awarded`. The dispute moves `EVIDENCE_REVIEW → AMENDED` and the scored item moves `UNDER_DISPUTE → AMENDED`, recording the granted figure as `amended_points_awarded`. `effective_points_awarded` now reads from `amended_points_awarded` rather than `points_awarded`, and `is_violation` and `severity` are re-derived from it. That re-derivation then propagates outward in the order given in §2.7: the parent visit's section percents, `critical_violation_count`, `critical_penalty_points`, `FINAL` composite score, and `grade` are recomputed; the location's `standing_score`, `latest_grade`, and `repeat_violation_count` follow; when the amendment drops the item out of `CRITICAL` severity, the non-terminal corrective action on that item is driven to `VOIDED`, which lowers the location's `open_corrective_action_count` and, if that action had already escalated, appends a `VOID_REVERSAL` ledger entry that steps `escalation_level` back down and re-derives `franchise_agreement_status`; and finally the brand's `brand_risk_index` is recomputed. Both `AMENDED` and `UPHELD` are terminal for the scored item.

A franchisee may abandon an appeal at any point before resolution. Withdrawal is available from `FILED`, from `INFO_REQUESTED`, and from `EVIDENCE_REVIEW`, accepts an optional `note`, requires that the acting franchisee be the dispute's `filed_by_franchisee_id`, stamps `resolved_at`, moves the dispute to `WITHDRAWN`, and returns the scored item `UNDER_DISPUTE → SCORED` so that it becomes disputable again and its visit becomes finalizable, rescorable, and voidable again. Disputes can be listed and filtered by `scored_item_id`, `filed_by_franchisee_id`, `reviewer_auditor_id`, and `status`.

### 3.8. Auditor Calibration, Reliability, and Certification

Auditor drift is measured by pairing a shadow audit against the visit it shadowed. An **Auditor** is registered with a `full_name` of 1 to 120 characters and an `employee_code` of 3 to 12 characters that must be globally unique; a duplicate reports `ERR_DUPLICATE_RESOURCE_CODE`. New auditors enter with `status` `PROVISIONAL`, `reliability_score` 70.00, `certification_period_start` null, `suspension_reason` null, and `finalized_visit_count` 0.

Once both a shadow visit and its target carry composite scores, a `CalibrationReviewer` records a **CalibrationRecord** by naming the `shadow_visit_id`. The server derives the rest: `primary_visit_id` is the shadow visit's `shadow_of_visit_id` target, `auditor_id` is the primary visit's auditor — the party whose reliability this record adjusts — `reviewer_auditor_id` is the shadow visit's auditor acting in the review seat, and `recorded_at` is the logical clock. The named visit must have `visit_type` `SHADOW`, must have a non-null `shadow_of_visit_id`, and both visits must carry a non-null `composite_score`; any of those failing reports `ERR_CALIBRATION_INPUTS_INCOMPLETE`. Only one calibration record may ever exist per shadow visit, and a second attempt is rejected with `ERR_CALIBRATION_ALREADY_RECORDED`. The recording reviewer must not be suspended (`ERR_AUDITOR_SUSPENDED`) and, per §2.10, may not be the audited auditor themselves (`ERR_SEGREGATION_OF_DUTIES`).

`variance_points` is the absolute difference between the shadow visit's `composite_score` and the primary visit's `composite_score`, rounded half up to two decimal places. That variance falls into one of four bands, each with a signed `reliability_delta`, and each band's upper bound is inclusive: a variance of at most 2.00 points is `EXCELLENT` and credits 4.00; a variance of at most 5.00 points is `ACCEPTABLE` and credits 1.00; a variance of at most 10.00 points is `MARGINAL` and debits 3.00; anything above 10.00 points is `UNACCEPTABLE` and debits 8.00. The `band` and `reliability_delta` are stored on the record.

`Auditor.reliability_score` is then recomputed under the **`ROLLING`** variant, which is the variant persisted on the auditor. Collect the calibration records naming this auditor as the audited party — never those naming them as `reviewer_auditor_id` — order them by `recorded_at` descending with `created_at` descending as the tiebreaker, and keep at most the three newest. Weight them by recency: the newest record's `reliability_delta` counts at full strength, the second at six tenths, the third at three tenths. Add those three weighted deltas to a baseline of 70.00, round half up to two decimal places, and clamp the result into the range 0.00 through 100.00. If the recomputed rolling score of a `CERTIFIED` auditor falls below 60.00, the system immediately suspends that auditor as a cascade, advancing `CERTIFIED → SUSPENDED` with `suspension_reason` `RELIABILITY_BELOW_FLOOR`.

Certification is evaluated under a materially different **`CERTIFICATION_REVIEW`** variant, and the gap between the two is intentional. When the compliance office certifies or re-certifies an auditor, the system collects every calibration record naming that auditor as the audited party whose `recorded_at` falls at or after the auditor's `certification_period_start` — all of them, with no window cap — adds their `reliability_delta` values at full weight to the same 70.00 baseline, rounds half up to two decimal places, and clamps to the range 0.00 through 100.00. Because nothing is dropped and nothing is decayed, this figure can read quite differently from the stored rolling score. Certification requires it to be at least 70.00; a lower figure is rejected with `ERR_RELIABILITY_BELOW_FLOOR`.

Certification advances `PROVISIONAL → CERTIFIED` for a new auditor and `SUSPENDED → CERTIFIED` for a reinstated one; either way it sets `certification_period_start` to the logical clock and clears `suspension_reason`. Resetting `certification_period_start` also restarts the certification-review window, so a reinstated auditor is judged only on calibration recorded after reinstatement. Suspension by the compliance office advances `CERTIFIED → SUSPENDED` or `PROVISIONAL → SUSPENDED`, accepts an optional `note`, and sets `suspension_reason` to `MANUAL_REVIEW` — the manual path always records `MANUAL_REVIEW`, while only the reliability cascade records `RELIABILITY_BELOW_FLOOR`. Certifying an already-certified auditor or suspending an already-suspended one is rejected with `ERR_INVALID_AUDITOR_STATE`.

Suspension has an immediate operational blast radius. Every `IN_PROGRESS` visit of the suspended auditor is driven `IN_PROGRESS → VOIDED` with `void_reason` `AUDITOR_SUSPENDED`; the auditor's `SCHEDULED` visits, by contrast, are left exactly where they are and are instead blocked at the moment someone tries to start them, with `ERR_AUDITOR_SUSPENDED`. Calibration records can be read back for a given auditor — in which case records naming them either as audited party or as reviewer are returned — or for a given visit, in which case records whose shadow visit or primary visit is that visit are returned.

### 3.9. Location Standing, Voids, Cures, and Brand-Level Risk

**Standing score.** A location's `standing_score` is a recency-weighted view of its recent audit history, recomputed on visit finalize, visit void, dispute amendment, and cure acceptance. Collect the location's `FINALIZED` visits whose `visit_type` is not `SHADOW`, order them by `finalized_at` descending with `created_at` descending as the tiebreaker, and keep at most the three most recent; voided, submitted, in-progress, and scheduled visits are all excluded. If that set is empty, `standing_score` is 0.00 and `latest_grade` is null, and the computation stops there. Otherwise the recency weights one half, three tenths, and one fifth are truncated to the number of visits actually available and then renormalized by dividing each by the sum of the truncated weights — so a location with only two finalized visits weights them five eighths and three eighths. Multiply each visit's `composite_score` by its renormalized weight, sum the products, and round half up to two decimal places; the renormalized weights themselves are carried at full precision and this is the single rounding step. That figure is the pre-penalty base.

The repeat-violation penalty is then keyed off that **pre-penalty base**, never off the post-penalty result: the per-unit deduction is 0.50 when the base is at least 90.00, 1.00 when the base is at least 80.00, and 2.00 otherwise. Multiply that per-unit figure by the location's `repeat_violation_count`, subtract the product from the base, round half up to two decimal places, and take the greater of the result and 0.00. `latest_grade` is set to the `grade` of the most recent visit in the ordered set.

**Voiding a visit.** A void is available from four states and its reversal set depends entirely on which state the visit is voided from; in every case a `void_reason` of `AUDITOR_SUSPENDED`, `RUBRIC_DEFECT`, or `SCHEDULING_ERROR` must be supplied, and an omitted reason is rejected with `ERR_INVALID_REQUEST`. Voiding from `SCHEDULED` records the `void_reason` and does nothing else, because nothing was ever scored. Voiding from `IN_PROGRESS` records the `void_reason` and deletes no scored item, but every scored item of the visit permanently stops contributing to any calculation; this is also the branch the auditor-suspension cascade uses. Voiding from `SUBMITTED` additionally requires that no scored item be `UNDER_DISPUTE` (`ERR_UNRESOLVED_DISPUTE`) and clears `composite_score`, `composite_variant`, and `grade` back to null; no location field moves, because only provisional numbers had ever existed.

Voiding from `FINALIZED` is the compensating branch and does the most work. It requires that no scored item be `UNDER_DISPUTE` and that no corrective action created by this visit be `VERIFIED` — a verified remediation is a fact about the world that a void cannot retract, so the attempt is rejected with `ERR_VERIFIED_ACTION_BLOCKS_VOID`. When permitted, the void records the `void_reason` and clears `composite_score`, `composite_variant`, `grade`, and `health_component_percent` to null; lowers the scoring auditor's `finalized_visit_count` by one; drives every non-terminal corrective action created by this visit to `VOIDED`, each of which lowers the location's `open_corrective_action_count` by one; appends exactly one `VOID_REVERSAL` ledger entry for each escalation entry this visit had itself appended, each of which lowers `escalation_level` by one and re-derives `franchise_agreement_status`; and finally recomputes the location's `standing_score`, `latest_grade`, and `repeat_violation_count`, and then the brand's `brand_risk_index`. The escalation entries originating from a particular visit can be read back on their own, which is how an operator inspects exactly what a void will have to compensate.

**Agreement consequences and cures.** The four agreement statuses are reached only as system cascades off the ledger. When the ledger drives `escalation_level` to exactly 1, the location moves `GOOD_STANDING → NOTICE_OF_DEFAULT` and both `Franchisee.open_default_location_count` and `Brand.default_location_count` are recomputed. When the level reaches exactly 2, the location moves `NOTICE_OF_DEFAULT → CURE_PERIOD` and `cure_period_started_at` is stamped with the logical clock. When the level reaches 3 or more, the location moves `CURE_PERIOD → TERMINATION_RECOMMENDED` and `Franchisee.termination_recommended` is set to true.

The compliance office can step a location back down by accepting a cure, which takes an optional `note`. Acceptance requires that the location's `open_corrective_action_count` be exactly 0 — every outstanding remediation must be verified, voided, or escalated out of the open pool first — and an attempt with open actions is rejected with `ERR_OPEN_CORRECTIVE_ACTIONS`. An attempt against a location already in `GOOD_STANDING` is rejected with `ERR_NO_ESCALATION_TO_CURE`. Accepting a cure from `CURE_PERIOD` appends a `CURE_ACCEPTED` ledger entry, which lowers `escalation_level` by one, re-derives `franchise_agreement_status` to `NOTICE_OF_DEFAULT`, and clears `cure_period_started_at`; this is the `NOTICE_OF_DEFAULT → CURE_PERIOD → NOTICE_OF_DEFAULT` cycle that lets a location work its way back. Accepting a cure from `NOTICE_OF_DEFAULT` appends a `CURE_ACCEPTED` entry that lowers `escalation_level` to 0, re-derives `franchise_agreement_status` to `GOOD_STANDING`, and recomputes `Franchisee.open_default_location_count`, `Brand.default_location_count`, and `Brand.brand_risk_index`. A location's own ledger can be read back in full by the compliance office and by its franchisee.

**Brand risk index.** The cross-location risk figure is recomputed on visit finalize, visit void, dispute amendment, corrective-action verify, corrective-action escalation, and cure acceptance — and also whenever the computed risk read is taken, which recomputes the index and persists the fresh result on the brand before returning it. Only *rated* locations participate: those whose `latest_grade` is not null, meaning they have at least one finalized visit. Unrated locations neither raise nor dilute the index. If no location of the brand is rated, `brand_risk_index` is 0.00 and `brand_risk_tier` is `BASELINE`, and the computation stops.

Otherwise, average the `standing_score` of the rated locations — sum them, divide by the number of rated locations, and round half up to two decimal places — and subtract that average from 100.00 to obtain the standing deficit. Four contributions are then summed. The deficit contributes six tenths of its value. The open-critical contribution is 6.00 for each corrective action of the brand whose `severity` is `CRITICAL` and whose `status` is one of `ASSIGNED`, `SUBMITTED`, `REJECTED`, `OVERDUE`, or `ESCALATED`, capped at 40.00 in total. The default contribution is 10.00 for each location counted in the brand's `default_location_count`, capped at 30.00 in total. The failing-grade surcharge is a flat 15.00 when any rated location's `latest_grade` is `FAIL`, and 0.00 otherwise. Add the four, round half up to two decimal places, and cap the result at 100.00; that is `brand_risk_index`. The tier follows: an index of at least 60.00 is `SEVERE`, an index of at least 35.00 is `ELEVATED`, and anything lower is `BASELINE`.

The computed risk read exposes the components alongside the headline figure so that a brand can see why its number moved: `brand_id`, `brand_risk_index`, `brand_risk_tier`, `average_standing_score`, `rated_location_count`, `open_critical_action_count`, `default_location_count`, and `fail_grade_surcharge_applied`.

## 4. Endpoint Definitions

Operations that bring a new resource into existence — registering a brand, franchisee, auditor, or location, drafting a rubric version, appending a rubric line item, scheduling a visit, scoring an item, attaching a photo, filing a dispute, importing an inspection, or recording calibration — return `201 Created`. Every other operation, including all state transitions on existing resources, the overdue sweep, the computed risk read, and the clock control, returns `200 OK` on success.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/brands` | Register a restaurant brand | BrandAdmin |
| GET | `/brands/{id}` | Read a brand including its current risk index and version | BrandAdmin, ComplianceIntegrator |
| GET | `/brands/{id}/risk-index` | Computed read of the cross-location brand risk index and its components | BrandAdmin |
| POST | `/franchisees` | Register a franchisee under a brand | BrandAdmin |
| GET | `/franchisees/{id}` | Read a franchisee including default counters | BrandAdmin, Franchisee |
| GET | `/franchisees` | List franchisees, optionally filtered by brand | BrandAdmin |
| POST | `/auditors` | Register an auditor; new auditors start PROVISIONAL with reliability_score 70.00 | BrandAdmin |
| GET | `/auditors/{id}` | Read an auditor including status and reliability_score | BrandAdmin, Auditor, CalibrationReviewer |
| POST | `/auditors/{id}/certify` | Certify or re-certify an auditor; gated on the CERTIFICATION_REVIEW reliability variant | BrandAdmin |
| POST | `/auditors/{id}/suspend` | Suspend an auditor for manual review | BrandAdmin |
| GET | `/auditors/{id}/calibration-records` | Calibration records naming this auditor as audited party or reviewer | BrandAdmin, Auditor, CalibrationReviewer |
| POST | `/locations` | Register a location operated by a franchisee of the same brand | BrandAdmin |
| GET | `/locations/{id}` | Read a location including standing_score, escalation_level, and franchise_agreement_status | BrandAdmin, Franchisee, Auditor |
| GET | `/locations` | List locations for cross-location trend reporting | BrandAdmin, Franchisee |
| GET | `/locations/{id}/health-inspections` | Health-department inspections recorded against this location | BrandAdmin, ComplianceIntegrator, Auditor |
| GET | `/locations/{id}/escalation-events` | Append-only escalation ledger of this location | BrandAdmin, Franchisee |
| POST | `/locations/{id}/cure-acceptance` | Accept a franchisee's cure and step the escalation level down by one | BrandAdmin |
| POST | `/rubric-versions` | Draft a rubric version for a brand, optionally superseding an existing one | BrandAdmin |
| GET | `/rubric-versions/{id}` | Read a rubric version | BrandAdmin, Auditor |
| GET | `/rubric-versions` | List rubric versions, including successors of a given version | BrandAdmin, Auditor |
| POST | `/rubric-versions/{id}/rubric-items` | Append a scoring line item to a DRAFT rubric version | BrandAdmin |
| GET | `/rubric-versions/{id}/rubric-items` | List the line items of a rubric version in display_order | BrandAdmin, Auditor |
| POST | `/rubric-versions/{id}/publish` | Publish a DRAFT rubric version and retire the version it supersedes | BrandAdmin |
| POST | `/audit-visits` | Schedule an announced, unannounced, or shadow visit | BrandAdmin |
| GET | `/audit-visits/{id}` | Read a visit including section percents, composite score, variant, and grade | BrandAdmin, Auditor, CalibrationReviewer, Franchisee |
| GET | `/audit-visits` | List visits for the audit calendar and for shadow/health linkage lookups | BrandAdmin, Auditor, CalibrationReviewer, Franchisee |
| POST | `/audit-visits/{id}/start` | Begin an on-site visit | Auditor |
| POST | `/audit-visits/{id}/scored-items` | Score one rubric line item on an IN_PROGRESS visit | Auditor |
| POST | `/audit-visits/{id}/submit` | Submit scores and compute the PROVISIONAL composite | Auditor |
| POST | `/audit-visits/{id}/rescore` | Correct one scored item on a SUBMITTED visit under optimistic concurrency | Auditor |
| POST | `/audit-visits/{id}/finalize` | Finalize a visit, admit health-department data, and assign corrective actions | BrandAdmin |
| POST | `/audit-visits/{id}/void` | Void a visit; the reversal set depends on the state the visit is voided from | BrandAdmin |
| GET | `/audit-visits/{id}/calibration-records` | Calibration records whose shadow or primary visit is this visit | BrandAdmin, CalibrationReviewer |
| GET | `/audit-visits/{id}/escalation-events` | Escalation ledger entries originating from this visit | BrandAdmin |
| GET | `/scored-items/{id}` | Read a scored item including dispute status and effective points | BrandAdmin, Auditor, Franchisee |
| GET | `/scored-items` | List scored items by visit or rubric item | BrandAdmin, Auditor, Franchisee |
| GET | `/corrective-actions/{id}` | Read a corrective action including due_at and counters | BrandAdmin, Auditor, Franchisee |
| GET | `/corrective-actions` | List corrective actions by scored item, location, or franchisee | BrandAdmin, Auditor, Franchisee |
| POST | `/corrective-actions/{id}/submit` | Franchisee submits remediation evidence for verification | Franchisee |
| POST | `/corrective-actions/{id}/verify` | Auditor accepts or rejects submitted remediation evidence | Auditor |
| GET | `/corrective-actions/{id}/evidence-photos` | Photos attached to a corrective action | BrandAdmin, Auditor, Franchisee |
| GET | `/corrective-actions/{id}/escalation-events` | Escalation ledger entries originating from this corrective action | BrandAdmin, Franchisee |
| POST | `/evidence-photos` | Attach a photo to exactly one corrective action or dispute | Franchisee, Auditor |
| POST | `/disputes` | Franchisee appeals a scored item on a FINALIZED visit | Franchisee |
| GET | `/disputes/{id}` | Read a dispute including info_request_count and resolution | BrandAdmin, Franchisee, CalibrationReviewer |
| GET | `/disputes` | List disputes by scored item, filer, or reviewer | BrandAdmin, Franchisee, CalibrationReviewer |
| GET | `/disputes/{id}/evidence-photos` | Photo evidence attached to this dispute, oldest first | BrandAdmin, Franchisee, CalibrationReviewer |
| POST | `/disputes/{id}/request-info` | Calibration reviewer requests additional information, capped at two rounds | CalibrationReviewer |
| POST | `/disputes/{id}/supplement` | Franchisee supplies evidence and moves the dispute to evidence review | Franchisee |
| POST | `/disputes/{id}/resolve` | Calibration reviewer upholds or amends the scored item | CalibrationReviewer |
| POST | `/disputes/{id}/withdraw` | Franchisee withdraws an unresolved dispute | Franchisee |
| POST | `/health-inspections` | Import a health-department inspection result | ComplianceIntegrator |
| GET | `/health-inspections/{id}` | Read a health inspection | BrandAdmin, ComplianceIntegrator |
| POST | `/health-inspections/{id}/disregard` | Exclude an inspection from composite selection | ComplianceIntegrator |
| POST | `/calibration-records` | Record shadow-audit calibration for a completed shadow visit and adjust the audited auditor's reliability | CalibrationReviewer |
| POST | `/overdue-sweeps` | Advance every past-due corrective action to OVERDUE and cascade CRITICAL ones to ESCALATED | BrandAdmin |
| POST | `/_clock/set_current_utc` | Test-driving endpoint that sets the server's logical clock | BrandAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_ACTING_IDENTITY_NOT_FOUND` | 404 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_BRAND_NOT_FOUND` | 404 |
| `ERR_FRANCHISEE_NOT_FOUND` | 404 |
| `ERR_AUDITOR_NOT_FOUND` | 404 |
| `ERR_LOCATION_NOT_FOUND` | 404 |
| `ERR_RUBRIC_VERSION_NOT_FOUND` | 404 |
| `ERR_RUBRIC_ITEM_NOT_FOUND` | 404 |
| `ERR_VISIT_NOT_FOUND` | 404 |
| `ERR_SCORED_ITEM_NOT_FOUND` | 404 |
| `ERR_CORRECTIVE_ACTION_NOT_FOUND` | 404 |
| `ERR_DISPUTE_NOT_FOUND` | 404 |
| `ERR_HEALTH_INSPECTION_NOT_FOUND` | 404 |
| `ERR_INVALID_VISIT_STATE` | 409 |
| `ERR_INVALID_CORRECTIVE_ACTION_STATE` | 409 |
| `ERR_INVALID_DISPUTE_STATE` | 409 |
| `ERR_INVALID_RUBRIC_STATE` | 409 |
| `ERR_INVALID_AUDITOR_STATE` | 409 |
| `ERR_NO_ESCALATION_TO_CURE` | 409 |
| `ERR_RUBRIC_VERSION_NOT_PUBLISHED` | 409 |
| `ERR_STALE_BRAND_VERSION` | 412 |
| `ERR_STALE_VISIT_VERSION` | 412 |
| `ERR_AUDITOR_SUSPENDED` | 409 |
| `ERR_AUDITOR_NOT_CERTIFIED` | 409 |
| `ERR_UNRESOLVED_DISPUTE` | 409 |
| `ERR_FRANCHISEE_BRAND_MISMATCH` | 422 |
| `ERR_RUBRIC_ITEM_NOT_IN_VISIT_RUBRIC` | 422 |
| `ERR_SHADOW_LINK_MISMATCH` | 422 |
| `ERR_SHADOW_TARGET_INVALID` | 422 |
| `ERR_EVIDENCE_TARGET_AMBIGUOUS` | 422 |
| `ERR_CALIBRATION_INPUTS_INCOMPLETE` | 422 |
| `ERR_INVALID_VISIT_WINDOW` | 422 |
| `ERR_ANNOUNCED_NOTICE_TOO_SHORT` | 422 |
| `ERR_RUBRIC_NOT_EFFECTIVE` | 422 |
| `ERR_TIMESTAMP_IN_FUTURE` | 422 |
| `ERR_AUDITOR_SCHEDULE_CONFLICT` | 409 |
| `ERR_LOCATION_VISIT_WINDOW_QUOTA` | 409 |
| `ERR_VISIT_WINDOW_NOT_OPEN` | 409 |
| `ERR_UNANNOUNCED_MIX_BELOW_MINIMUM` | 422 |
| `ERR_POINTS_EXCEED_MAX` | 422 |
| `ERR_ITEM_ALREADY_SCORED` | 409 |
| `ERR_CRITICAL_ITEMS_UNSCORED` | 422 |
| `ERR_RESCORE_LIMIT_REACHED` | 409 |
| `ERR_RUBRIC_TOTAL_MISMATCH` | 422 |
| `ERR_RUBRIC_SECTION_INCOMPLETE` | 422 |
| `ERR_DISPUTE_POINTS_INVALID` | 422 |
| `ERR_DISPUTE_ALREADY_OPEN` | 409 |
| `ERR_INFO_REQUEST_LIMIT_REACHED` | 409 |
| `ERR_EVIDENCE_REQUIRED` | 422 |
| `ERR_LATE_CURE_NOT_ALLOWED` | 409 |
| `ERR_OPEN_CORRECTIVE_ACTIONS` | 409 |
| `ERR_RELIABILITY_BELOW_FLOOR` | 409 |
| `ERR_VERIFIED_ACTION_BLOCKS_VOID` | 409 |
| `ERR_CALIBRATION_ALREADY_RECORDED` | 409 |
| `ERR_DUPLICATE_RESOURCE_CODE` | 409 |
| `ERR_DUPLICATE_RUBRIC_ENTRY` | 409 |

# Utility Easement Encroachment API — Product Requirements Document

## 1. Introduction

Electric and pipeline utilities hold thousands of easement strips across private land, and every strip is a slow-moving legal exposure: fences creep over the line, landowners build sheds inside the corridor, vegetation grows into the wire zone, and new transmission projects demand freshly acquired strips whose compensation must be negotiated, budgeted, and — when negotiation fails — condemned. The right-of-way department currently tracks this work across county recorder filings, GIS sketches, and spreadsheets, which makes it impossible to answer basic questions with confidence: which cases have clean title, how much acquisition budget is still uncommitted, which encroachments are aging into litigation risk, and which third-party permits overlap in time and space.

This document specifies the Utility Easement Encroachment API, the system of record for that department. The API organizes all work under the **Easement Case**, an aggregate rooted at a single easement strip on a single parcel, and governs the full operational arc: assembling the recorded document inventory and clearing title; discovering encroachments and driving them through notification, negotiation, removal, waiver, retroactive permitting, or escalation to counsel; acquiring new easement area through budgeted, segregation-of-duties-controlled compensation offers; enforcing vegetation height and species limits zone by zone; and closing cases through resolution, condemnation, or abandonment. All resources are mounted under the `/easement-cases` prefix.

The design treats the case as a derived-state aggregate: its status, budget balance, open-encroachment count, pressure score, title-clearance flag, and active-permit count are continuously reconciled from the states of its children, and several child operations re-verify their view of the case through optimistic concurrency before they are allowed to commit. Readers should treat Section 2 as the binding structural contract and Section 3 as the complete behavioral specification; the two are written to be reconstructed into a single consistent implementation.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. The system recognizes exactly five roles, spelled precisely as follows: `RightOfWayAgent`, `TitleExaminer`, `VegetationInspector`, `LitigationCounsel`, and `DepartmentDirector`. A request whose `X-User-Role` header is missing or does not match one of these five values is rejected with `ERR_MISSING_OR_INVALID_ROLE` (HTTP 401). A request whose role is valid but not permitted for the targeted endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403); the per-endpoint role assignments are listed in Section 4.

For every role in this system, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on certain resources for audit purposes — for example, as `ordered_by` and `completed_by` on a title search, as `referred_by` on a litigation referral created by a `RightOfWayAgent`, and as `accepted_by` when a `LitigationCounsel` accepts a referral — but it never compares `X-User-ID` to any entity's `id`. The one place identity comparison matters is segregation of duties on acquisition offers: the system remembers which opaque user identifier created an offer and uses that remembered value, not any entity linkage, to enforce the self-approval prohibition described in §3.5.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and accepts a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of every list response carries exactly the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Case as a Derived-State Aggregate

An Easement Case is not a free-standing status flag; it is a continuous reconciliation of everything happening underneath it. Several of its fields are computed rather than written directly: `compensation_committed_cents` aggregates the acquisition offers that currently encumber the budget; `compensation_balance_cents` is always the `acquisition_budget_cents` minus `compensation_committed_cents`; `open_encroachment_count` counts the encroachments that have not reached a terminal state; `encroachment_pressure_score` aggregates the severity and age of unresolved encroachments; `title_cleared` reflects the latest title search together with the recorded-document inventory; and `active_permit_count` counts permits whose `approval_status` is `APPROVED` and whose `field_inspection_status` is anything other than `FAILED`. Whenever a child event changes one of these inputs, the server recomputes the derived value immediately, and each such recomputation is a mutation of the case: it refreshes the case's `updated_at` and increments its `version`.

The same reconciliation principle drives automatic state movement in both directions. The arrival of the first unresolved encroachment pulls a monitoring case into resolution work, and the retirement of the last unresolved encroachment releases it back to monitoring. Certain child transitions cascade sideways as well: recording a superseding document pushes the superseded one out of the active inventory, approving a retroactive permit resolves the encroachment it legalizes, and recording a failed inspection can strip a permit of its approval. To uphold these invariants the server transitions parent or sibling resources automatically when the stated criteria are satisfied, without requiring an explicit client request on the affected resource. No child resource may be created or transitioned once its case has reached a terminal closed state; such attempts are rejected with `ERR_CASE_ALREADY_CLOSED`.

### 2.5. Common Resource Properties

Every resource in the system — cases, documents, encroachments, offers, permits, vegetation zones, vegetation violations, title searches, and litigation referrals — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits (for example, `2026-08-01T09:15:00.123Z`), set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `status`-family fields and `version` (integer): the `version` starts at 1 and increments on every mutation, and is the field on which optimistic concurrency control operates.

Because recomputation of a derived field is a mutation, an event such as an encroachment being reported against a case advances the case's `version` even though the client never wrote to the case directly. Clients that hold a case `version` for concurrency purposes must expect it to move whenever the system reconciles any derived field on that case.

### 2.6. Monetary Values, Scores, and Rounding Discipline

All money in the system is represented as integer cents — never fractional dollars. This applies to the case's `fair_market_value_per_sqft` inputs when converted into compensation, the `acquisition_budget_cents` cap and its committed and balance derivatives, every compensation figure on an acquisition offer (`base_compensation_cents`, `negotiated_compensation_cents`, `severance_damages_cents`, `total_compensation_cents`), the `estimated_removal_cost_cents` on an encroachment, and the `annual_fee_cents` on a permit. Wherever a monetary calculation produces a fractional cent — notably the base compensation computation, which multiplies square footage by a per-square-foot value and by 100 — the result is rounded half-up to the nearest whole cent.

Non-monetary computed values carry their own precision contracts. The raw severity score behind an encroachment's `severity_tier` is computed to 3 decimal places, and tier boundaries are pinned at their exact thresholds with at-least semantics. The case-level `encroachment_pressure_score` is rounded half-up to 2 decimal places. A vegetation violation's `excess_height_ft` is rounded half-up to 1 decimal place. These rounding rules are part of the observable contract: two implementations that round differently will produce visibly different API output.

### 2.7. Optimistic Concurrency Control on Case-Sensitive Writes

Three write operations are considered case-sensitive because their eligibility depends on derived case state (title clearance, compensation balance, encroachment severity) that other writers can legitimately change. Each of these three operations requires a non-optional `expected_case_version` field in its request body, carrying the `version` of the parent case as the client last observed it:

1. Tendering an acquisition offer.
2. Approving a third-party permit.
3. Sending an encroachment notice.

On any of these three, if the supplied `expected_case_version` does not match the case's current `version` — because another writer has since recorded a document, reported an encroachment, or otherwise advanced the case — the request is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412). The rationale differs per operation but the mechanism is identical: a newly recorded document can flip `title_cleared` or free budget; a newly discovered encroachment changes the permit-approval context; and a superseding document can re-derive an encroachment's `severity_tier`, so a notifier working from a stale severity view must not silently succeed. Each of these three operations, when it succeeds, itself increments the case's `version` by 1. Endpoints not named in this section do not accept a version field at all; optimistic concurrency in this system exists only for the case, only on these three writes.

### 2.8. Validation Pipeline and Evaluation Order

When several rules could reject the same request, the order in which they are evaluated is part of the contract, because the order determines which `error_id` the client receives. The system evaluates checks in the following fixed sequence, returning the first failure encountered:

1. **Role presence and validity** — the `X-User-Role` header must be present and be one of the five declared roles, else `ERR_MISSING_OR_INVALID_ROLE` (401). This applies to every endpoint.
2. **Role permission** — the declared role must be authorized for the targeted endpoint, else `ERR_UNAUTHORIZED_ROLE` (403). This applies to every endpoint.
3. **Path existence** — resource identifiers in the path must exist, validated left to right (see §2.9), each miss producing its specific 404 error.
4. **Parent case openness** — the parent case must be in a state that permits the child operation, else the applicable one of `ERR_CASE_NOT_OPEN_FOR_RECORDING`, `ERR_CASE_NOT_MONITORING`, or `ERR_CASE_ALREADY_CLOSED` (409).
5. **Target resource state** — the resource being transitioned must currently be in the state the transition starts from, else the entity-specific state error such as `ERR_OFFER_NOT_TENDERED`, `ERR_ENCROACHMENT_NOT_NEGOTIATING`, `ERR_PERMIT_NOT_PENDING`, `ERR_TASK_NOT_IN_PROGRESS`, `ERR_DOCUMENT_NOT_DRAFT`, `ERR_REFERRAL_NOT_ACCEPTED`, or `ERR_REFERRAL_NOT_FILED` (409), with `ERR_INVALID_STATE` (409) as the generic form.
6. **Cross-case referential integrity** — a document or encroachment referenced by a new encroachment, permit, or referral must exist and belong to the same case, else `ERR_CROSS_CASE_REFERENCE` (409).
7. **Title-clearance safety** — recording a document, tendering an offer, or activating monitoring all require cleared title, else `ERR_TITLE_NOT_CLEARED` (409).
8. **Uniqueness and recording integrity** — instrument-number uniqueness per county, the requirement that a referenced document actually be `RECORDED`, and the prohibition on self-supersession, producing `ERR_DUPLICATE_INSTRUMENT_NUMBER`, `ERR_DOCUMENT_NOT_RECORDED`, or `ERR_SELF_SUPERSEDE` (409).
9. **Temporal validity** — a `recording_date` in the future, a permit window whose end does not come after its start, or a negotiation deadline already passed, producing `ERR_INVALID_DATE_RANGE` or `ERR_DEADLINE_PASSED` (422).
10. **Segregation of duties** — the self-tender prohibition and the director-approval requirement for high-compensation offers, producing `ERR_NEGOTIATOR_CANNOT_APPROVE_OWN_OFFER` or `ERR_DIRECTOR_APPROVAL_REQUIRED` (403).
11. **Negotiation-round discipline** — countering only while rounds remain and escalating only once they are exhausted, producing `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` or `ERR_NEGOTIATION_ROUNDS_NOT_EXHAUSTED` (409).
12. **Permit window overlap** — the temporal-overlap prohibition among approved permits on the same case, producing `ERR_PERMIT_OVERLAP` (409).
13. **Vegetation exemption safety** — the prohibited-species and excess-height limits on exemption, producing `ERR_PROHIBITED_SPECIES_NOT_EXEMPTABLE` or `ERR_EXCESS_HEIGHT_TOO_LARGE` (409).
14. **Fiscal adequacy** — the compensation offered must fit within the case's remaining balance, else `ERR_COMPENSATION_EXCEEDS_BUDGET` (402).
15. **Closure gate** — the case may close only when no open encroachments, open offers, pending permits, or pending litigation remain, producing `ERR_OPEN_ENCROACHMENTS_REMAIN`, `ERR_OPEN_OFFERS_EXIST`, `ERR_PENDING_PERMITS_EXIST`, or `ERR_PENDING_LITIGATION_EXISTS` (409).

The practical consequence is that a failure earlier in this list masks every later one: a request failing both role authorization and budget adequacy receives the role error, and a stale-version rejection under §2.7 is a distinct, separately reported condition carrying `ERR_STALE_CASE_VERSION` (412).

### 2.9. Nested Resource Retrieval and Flat Alternative Access

Paths in this API are hierarchical: a document lives under its case, a violation lives under its zone under its case, and so on. For any request whose path contains multiple identifiers, the system validates existence strictly left to right and stops at the first identifier that does not resolve. A request naming a nonexistent `caseId` is rejected with `ERR_CASE_NOT_FOUND` before any child identifier is examined; a valid `caseId` paired with a nonexistent `docId` yields `ERR_DOCUMENT_NOT_FOUND`; the analogous child misses yield `ERR_ENCROACHMENT_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, `ERR_TITLE_TASK_NOT_FOUND`, or `ERR_REFERRAL_NOT_FOUND` respectively, all HTTP 404.

Alongside every nested collection, the API also exposes a flat retrieval path for each child entity directly under the `/easement-cases` prefix (for example, a flat document lookup by `docId` alone, without a case segment). These flat endpoints return the same resource representations and exist so that cross-case filtered queries are possible: the flat document list filters by `case_id`, `supersedes_document_id`, `status`, and `doc_kind`; the flat encroachment list filters by `case_id`, `encroaches_document_id`, `status`, and `severity_tier`; the flat offer list filters by `case_id` and `status`; the flat permit list filters by `case_id`, `encroachment_id`, `approval_status`, and `permit_type`; the flat zone list filters by `case_id` and `status`; the flat violation list filters by `zone_id`, `case_id`, and `status`; the flat title-search list filters by `case_id` and `status`; and the flat referral list filters by `case_id`, `encroachment_id`, and `status`. All flat lists also accept `limit` and `offset`.

### 2.10. The Logical Clock and Deadline-Driven Automation

The system runs on a logical clock rather than wall-clock time. At startup the clock reads exactly 2026-08-01T00:00:00Z, and it must never silently fall back to wall-clock time. An administrative capability available to all five roles advances the clock: the caller supplies a `to_iso8601` instant, and the server responds with the resulting `current_utc`. Advancing the clock re-evaluates every deadline-based automatic transition in the system — expiring offers whose negotiation window has run out, escalating notified encroachments whose owner-response window has lapsed, and escalating notified vegetation violations whose remediation window has closed. All deadline arithmetic elsewhere in this document (response windows, negotiation windows, remediation windows, filing windows) is measured against this logical clock.

## 3. Business Logic & Workflows

### 3.1. Case Intake, Title Research, and the Road to Monitoring

A `RightOfWayAgent` opens a new **Easement Case** by supplying its identifying and fiscal facts: a unique human-readable `case_code` (such as ESM-2026-0142), the `utility_district` code, the `county`, the assessor's `parcel_id`, the strip's `easement_width_ft` and gross `easement_area_sqft`, the appraised `fair_market_value_per_sqft` used later for acquisition compensation, and the `acquisition_budget_cents` cap on new-easement compensation. A freshly created case starts in `INTAKE` with `compensation_committed_cents` at 0, `compensation_balance_cents` equal to the full `acquisition_budget_cents`, `open_encroachment_count` and `encroachment_pressure_score` at 0, `title_cleared` false, and `active_permit_count` at 0.

Title research runs as an explicit task queue on the case. A `TitleExaminer` orders a search by naming its `search_scope` — one of `FULL_CHAIN`, `CURRENT_OWNER`, or `LIEN_ONLY` — and the system records the examiner's opaque identifier in `ordered_by` and places the task in `ORDERED`. Beginning the work moves the task `ORDERED → IN_PROGRESS`; cancelling is possible only from `ORDERED` and leaves the task `CANCELLED`. Completion is the decisive act: the examiner submits `liens_found`, `defects_found` (each defaulting to 0 when omitted), and the structured `chain_of_title_json`, the system records the completer in `completed_by`, and the outcome forks on the numbers. When both counts are zero the task becomes `COMPLETED_CLEAN`; when either count is greater than zero the task becomes `COMPLETED_WITH_DEFECTS`. Attempting to complete a task as clean while reporting any liens or defects is rejected with `ERR_TITLE_DEFECTS_EXIST`, and attempting to complete a task that is not `IN_PROGRESS` is rejected with `ERR_TASK_NOT_IN_PROGRESS`.

The case's `title_cleared` flag is then derived, and the derivation is deliberately strict: it is true only when the most recently created title search for the case — latest by creation timestamp, with any tie broken by earlier `created_at` first and never by `id` — is `COMPLETED_CLEAN` **and** at least one document on the case is in `RECORDED` status. A clean search alone is insufficient; a recorded document must also exist. Completing a search with defects forces `title_cleared` to false and blocks any offer still in `DRAFT` on that case from being tendered until a clean search completes. Recording a document also recomputes the flag (see §3.2).

Two agent-driven transitions move the case forward. Beginning mapping moves `INTAKE → MAPPING` and requires that at least one document exist on the case, failing with `ERR_NO_DOCUMENTS_ON_CASE` otherwise. Activating monitoring moves `MAPPING → ACTIVE_MONITORING` and is the first enforcement of the title gate: it requires at least one `RECORDED` document (else `ERR_NO_RECORDED_DOCUMENT`) and a cleared title per the derivation above (else `ERR_TITLE_NOT_CLEARED`); on success it recomputes `title_cleared` and sets the case to `ACTIVE_MONITORING`. A case that should never have been opened can instead be abandoned: abandonment moves `INTAKE → CLOSED_ABANDONED`, is performed by a `DepartmentDirector`, and is permitted only while the case has no `RECORDED` document — if one exists the attempt fails with `ERR_RECORDED_DOCUMENT_EXISTS`, because a recorded interest can no longer simply be walked away from.

### 3.2. The Recorded Document Inventory, Encumbrance Priority, and Supersession

The document inventory is the legal spine of the case. A `TitleExaminer` adds a document in `DRAFT` status by supplying its `doc_kind` — one of `DEED`, `PLAT`, `AMENDMENT`, or `JUDGMENT` — together with the county recorder's `instrument_number`, the `recording_date`, the `grantor_name` and `grantee_name`, the `gis_polygon_wkt` footprint of the easement, the `width_ft` this document grants, and optionally a `supersedes_document_id` identifying an earlier document this one replaces (null when it replaces nothing). Two integrity rules guard creation and recording: the `supersedes_document_id` must reference a document that is itself `RECORDED` and must not equal the document's own `id` — violations produce `ERR_DOCUMENT_NOT_RECORDED` and `ERR_SELF_SUPERSEDE` respectively — and the `recording_date` may not lie in the future, else `ERR_INVALID_DATE_RANGE`. Documents are reachable both through their case and through the flat retrieval paths described in §2.9.

Recording is the examiners' pivotal act, moving a document `DRAFT → RECORDED`. It is allowed only while the case is in `MAPPING`, `ACTIVE_MONITORING`, or `RESOLUTION_PENDING` (else `ERR_CASE_NOT_OPEN_FOR_RECORDING`), and only while the `instrument_number` remains unique across the county (else `ERR_DUPLICATE_INSTRUMENT_NUMBER`). Recording a document that is not in `DRAFT` is rejected with `ERR_DOCUMENT_NOT_DRAFT`; a draft found defective is instead moved `DRAFT → REJECTED_DEFECTIVE` under the same state guard. On successful recording, three things happen. First, the document receives its `encumbrance_rank`: among the case's `RECORDED` documents, rank is the 1-based position when sorted by `recording_date` ascending, with ties broken by earlier `created_at` first and never by `id` — rank encodes recording priority, which governs conflicting encroachment claims. Second, if the newly recorded document names a `supersedes_document_id`, that earlier document is automatically moved `RECORDED → SUPERSEDED` and its rank is freed; a superseded document keeps its last rank only until the supersession actually executes. Third, the case's `title_cleared` is recomputed against the refreshed inventory.

Supersession has one further, easy-to-miss cascade. An encroachment always points at the specific recorded document whose strip it invades, via its `encroaches_document_id`, and that reference must point at a `RECORDED` document of the same case at creation time (see §3.3). When the referenced document is later superseded, the encroachment is not deleted or re-pointed — it remains attached to the superseded document — but its `severity_tier` is recomputed against the superseding document's `width_ft`. Because severity divides encroachment depth by the granted width, a narrower superseding grant can escalate a `MODERATE` encroachment to `SEVERE` without any new field activity, and a wider one can downgrade it. Every such recomputation also refreshes the case's `encroachment_pressure_score`.

### 3.3. Encroachment Discovery, Severity, and the Negotiation Loop

Encroachments are the operational heart of the monitoring phase. A `RightOfWayAgent` reports one against a case by supplying how it was found — `discovered_via`, one of `AERIAL_SURVEY`, `FIELD_INSPECTION`, `THIRD_PARTY_REPORT`, or `TITLE_SEARCH` — what it is — `encroachment_type`, one of `STRUCTURE`, `VEGETATION`, `FENCE`, `PAVEMENT`, `UTILITY_CROSSING`, or `OTHER` — its `encroachment_area_sqft`, its maximum perpendicular `depth_into_easement_ft`, the `encroaches_document_id` of the recorded document whose strip is invaded, and an `estimated_removal_cost_cents`. The referenced document must exist, belong to the same case (else `ERR_CROSS_CASE_REFERENCE`), and be `RECORDED` (else `ERR_DOCUMENT_NOT_RECORDED`). A new encroachment starts in `DISCOVERED`, and its arrival reconciles the case: `open_encroachment_count` increments, `encroachment_pressure_score` is recomputed, and the first open encroachment automatically pulls the case `ACTIVE_MONITORING → RESOLUTION_PENDING`.

The system derives each encroachment's `severity_tier` — one of `MINOR`, `MODERATE`, `SEVERE`, or `CRITICAL` — from a scoring rule with a deliberately non-linear interaction between depth and area. Two ratios are formed: the depth ratio, which is the `depth_into_easement_ft` divided by the `width_ft` of the encroached document, and the area ratio, which is the `encroachment_area_sqft` divided by the case's `easement_area_sqft`. Each encroachment type carries a base score: `UTILITY_CROSSING` starts at 4, `STRUCTURE` at 3, `FENCE` and `PAVEMENT` at 2, and `VEGETATION` and `OTHER` at 1. The depth contribution is then amplified by an area-driven multiplier: when the area ratio is at least 0.25 the multiplier is 2.0; when it is at least 0.10 but below 0.25 the multiplier is 1.5; below 0.10 the multiplier is 1.0 — depth matters more when the footprint is large. The raw score is the base score multiplied by one plus the product of the depth ratio and the multiplier, computed to 3 decimal places. The tier is pinned at exact thresholds with at-least semantics: a raw score of at least 6.0 is `CRITICAL`, at least 3.5 but below 6.0 is `SEVERE`, at least 1.8 but below 3.5 is `MODERATE`, and anything below 1.8 is `MINOR`. The tier is computed provisionally at creation against the currently recorded document's width and re-derived whenever that document is superseded (§3.2).

The case's `encroachment_pressure_score` aggregates everything still unresolved. For each encroachment on the case whose status is not one of `REMOVED`, `PERMITTED_RETROACTIVELY`, `WAIVED`, or `ESCALATED_TO_LEGAL`, the system takes a tier weight — 1 for `MINOR`, 3 for `MODERATE`, 7 for `SEVERE`, 15 for `CRITICAL` — and multiplies it by an age multiplier that compounds with neglect: the multiplier is 1 plus one-hundredth per whole day of age, where whole days of age is the floor of the elapsed time since the encroachment's `created_at`, and the age used is capped at 90 days so the multiplier never exceeds 1.9. The contributions are summed and the total is rounded half-up to 2 decimal places. The score is recomputed whenever an encroachment is created, reaches a terminal state, or changes tier.

From `DISCOVERED`, the agent sends the owner a notice, moving the encroachment `DISCOVERED → NOTIFIED`. This is one of the three case-sensitive writes of §2.7: the request must carry `expected_case_version` matching the case's current `version`, and a mismatch is rejected with `ERR_STALE_CASE_VERSION` (412). Notification also requires the case to be in `ACTIVE_MONITORING` or `RESOLUTION_PENDING` (else `ERR_CASE_NOT_MONITORING`). On success the system sets `owner_response_due_date` to the notification instant plus the configured `OWNER_RESPONSE_WINDOW_DAYS`, and the write increments the case's `version` by 1. If that due date passes with no negotiation begun, the system automatically escalates the encroachment `NOTIFIED → ESCALATED_TO_LEGAL` and auto-creates a litigation referral in `REFERRED` with `referral_reason` `NEGOTIATION_FAILED`.

Negotiation is a counted loop. Beginning negotiation moves `NOTIFIED → NEGOTIATING` and sets `negotiation_round` to 1. Recording a counter-offer moves `NEGOTIATING → COUNTERED` and increments `negotiation_round` by 1, but is permitted only while `negotiation_round` is still below the configured `MAX_NEGOTIATION_ROUNDS` — at the limit the counter is rejected with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`. Resuming after a counter moves `COUNTERED → NEGOTIATING` without consuming a round. Three exits close the loop. Agreement moves the encroachment from `NEGOTIATING` or `COUNTERED` to `REMOVAL_AGREED` (operations requiring `NEGOTIATING` or `COUNTERED` reject other states with `ERR_ENCROACHMENT_NOT_NEGOTIATING`); when the `encroachment_type` is `VEGETATION` and a linked vegetation violation exists, that violation is advanced to `NOTIFIED` as part of the agreement. Confirming the physical removal then moves `REMOVAL_AGREED → REMOVED`, permitted only while the case is in `ACTIVE_MONITORING` or `RESOLUTION_PENDING`; it decrements `open_encroachment_count`, recomputes the pressure score, and when the count reaches zero the case automatically returns `RESOLUTION_PENDING → ACTIVE_MONITORING`. Escalation is the adversarial exit: from `NEGOTIATING` or `COUNTERED` the agent may escalate to `ESCALATED_TO_LEGAL`, but only once the rounds are exhausted — `negotiation_round` must be at least `MAX_NEGOTIATION_ROUNDS`, else the attempt fails with `ERR_NEGOTIATION_ROUNDS_NOT_EXHAUSTED` — and escalation auto-creates a `REFERRED` litigation referral with `referral_reason` `NEGOTIATION_FAILED`.

One gentler exit exists for trivial cases: a `DepartmentDirector` may waive an encroachment, moving `NEGOTIATING → WAIVED`, but only when its `severity_tier` is `MINOR` — anything more serious is rejected with `ERR_ONLY_MINOR_WAIVABLE`. Waiving decrements `open_encroachment_count` and recomputes the pressure score, and like any terminal encroachment transition it can release the case back to monitoring when the count reaches zero.

### 3.4. Third-Party Permits and Retroactive Legalization

Not every intrusion must be removed; some are licensed to stay. A `RightOfWayAgent` requests a **Third-Party Permit** on a case by supplying the `permittee_name`, the `permit_type` — one of `DRIVEWAY`, `LANDSCAPING`, `FENCE_RETENTION`, `STRUCTURE_RETENTION`, or `UTILITY_CROSSING` — the `requested_area_sqft`, and the use window `requested_start_date` to `requested_end_date`. The window must be a valid half-open interval with the end strictly after the start, else `ERR_INVALID_DATE_RANGE`. When the permit legalizes an existing encroachment, the request also carries its `encroachment_id`, which must reference an encroachment of the same case (else `ERR_CROSS_CASE_REFERENCE`); for proactive permits the field is simply absent. Whether the permittee's liability insurance is on file is captured by `insurance_certificate_on_file`, defaulting to false. A new permit starts with `approval_status` `PENDING` and `field_inspection_status` `NOT_SCHEDULED` — two parallel dimensions that then evolve semi-independently.

The inspection dimension belongs to the `VegetationInspector`. Scheduling moves `field_inspection_status` `NOT_SCHEDULED → SCHEDULED` and requires the permit still be `PENDING` on the approval dimension. Recording the outcome carries a `result` of `PASSED` or `FAILED` and moves a `SCHEDULED` inspection to that outcome. A failed inspection is immediately consequential: if the permit's `approval_status` is `APPROVED` at that moment, the approval is automatically torn down to `REVOKED`.

Approval is the gated act, moving `approval_status` `PENDING → APPROVED`, and it is the second case-sensitive write of §2.7: the request must carry `expected_case_version`, rejected with `ERR_STALE_CASE_VERSION` (412) when the case has moved on, and success increments the case's `version` by 1. Approval is rejected with `ERR_PERMIT_NOT_PENDING` when the permit is no longer pending, and then faces four substantive gates. The case must be in `ACTIVE_MONITORING` or `RESOLUTION_PENDING` (else `ERR_CASE_NOT_MONITORING`). The inspection dimension must show `PASSED` (else `ERR_INSPECTION_NOT_PASSED`). Insurance must be on file (else `ERR_INSURANCE_REQUIRED`). And the requested window must not collide with any other `APPROVED` permit on the same case covering the same `permit_type` or an intersecting area, under a half-open overlap test in which touching intervals — one window's end exactly equal to another's start — do not overlap; a `STRUCTURE_RETENTION` permit additionally inflates both ends of its own window by a 30-day maintenance buffer before the comparison, while all other types compare their exact windows. A collision is rejected with `ERR_PERMIT_OVERLAP`. When the permit names an `encroachment_id`, that encroachment must be in `NEGOTIATING` or `COUNTERED` (else `ERR_ENCROACHMENT_NOT_NEGOTIATING`), and on approval the encroachment automatically becomes `PERMITTED_RETROACTIVELY`, decrementing `open_encroachment_count` and recomputing the pressure score. Approval also computes the permit's `annual_fee_cents` and recomputes the case's `active_permit_count`.

The fee is tiered and its rounding order is pinned. Each permit type carries a base annual rate in cents: 25,000 for `DRIVEWAY`, 10,000 for `LANDSCAPING`, 15,000 for `FENCE_RETENTION`, 50,000 for `STRUCTURE_RETENTION`, and 75,000 for `UTILITY_CROSSING`. To the base rate the system adds an area component computed in three brackets with per-bracket rounding before summation — this per-tier rounding, rather than sum-then-round, is the contract, and the two can differ by a couple of cents for areas straddling a bracket boundary. The first 500 square feet are charged at 12 cents per square foot, rounded half-up to whole cents. Square footage beyond 500 up to 2,000 is charged at 8 cents per square foot on the excess over 500, with the bracket total rounded half-up. Square footage beyond 2,000 is charged at 5 cents per square foot on the excess over 2,000, again with the bracket total rounded half-up. The annual fee is the base rate plus the applicable bracketed components.

Denial moves `PENDING → DENIED` without ceremony. Revocation is the `DepartmentDirector`'s tool for a permit that has failed in the field: it moves `APPROVED → REVOKED` and is allowed only when `field_inspection_status` is `FAILED`, else `ERR_ONLY_FAILED_INSPECTION_REVOKABLE`. Revocation recomputes `active_permit_count`, and when the revoked permit legalized an encroachment, that encroachment reverts to `NEGOTIATING` and `open_encroachment_count` increments — legalization undone becomes an open problem again.

### 3.5. Acquisition Offers and the Compensation Ledger

New easement area is bought, and the buying is a ledger. A `RightOfWayAgent` drafts an **Acquisition Offer** against a case by supplying the `landowner_name`, the `landowner_contact`, the `offered_area_sqft` to be acquired, and optionally `severance_damages_cents` for harm to the remainder parcel (defaulting to 0). At creation the system computes `base_compensation_cents` as the `offered_area_sqft` multiplied by the case's `fair_market_value_per_sqft` and by 100, rounded half-up to whole cents; initializes `negotiated_compensation_cents` to that base; computes `total_compensation_cents` as the negotiated amount plus `severance_damages_cents`; initializes `negotiation_round` to 0; and derives `requires_director_approval`, which is true exactly when `total_compensation_cents` reaches or exceeds the configured `DIRECTOR_APPROVAL_THRESHOLD_CENTS`. The offer rests in `DRAFT`.

Tendering moves `DRAFT → TENDERED` and is the third case-sensitive write of §2.7: `expected_case_version` must match the case's current `version` or the tender is rejected with `ERR_STALE_CASE_VERSION` (412), and a successful tender increments the case's `version` by 1. The substantive gates run in the pipeline order of §2.8: the case must be in `MAPPING`, `ACTIVE_MONITORING`, or `RESOLUTION_PENDING`; `title_cleared` must be true (else `ERR_TITLE_NOT_CLEARED`); segregation of duties forbids the user who created the offer from tendering it when `requires_director_approval` is true (else `ERR_NEGOTIATOR_CANNOT_APPROVE_OWN_OFFER`, 403); and the offer's `total_compensation_cents` must not exceed the case's current `compensation_balance_cents` (else `ERR_COMPENSATION_EXCEEDS_BUDGET`, 402). On success the tender commits funds: `compensation_committed_cents` increases by the offer's `total_compensation_cents`, `compensation_balance_cents` is recomputed, and `negotiation_deadline` is set to the tender instant plus the configured `NEGOTIATION_WINDOW_DAYS`.

The committed ledger has a precise membership rule. `compensation_committed_cents` is always the sum of `total_compensation_cents` over exactly the offers in `TENDERED`, `COUNTERED`, or `ACCEPTED` status, and `compensation_balance_cents` is `acquisition_budget_cents` minus that sum. During negotiation the view is provisional — a tendered or countered offer's current negotiated total encumbers the budget — and rejected, withdrawn, or expired offers release their commitment back to the balance, while accepted offers remain committed until the case closes.

Negotiation over price mirrors the encroachment loop. Countering a `TENDERED` offer carries a `counter_amount_cents`, moves the offer `TENDERED → COUNTERED`, and is permitted only while `negotiation_round` remains below `MAX_NEGOTIATION_ROUNDS` (else `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`); countering after the `negotiation_deadline` has passed is rejected with `ERR_DEADLINE_PASSED` (422). A counter increments `negotiation_round` by 1, overwrites `negotiated_compensation_cents` with the counter amount, recomputes `total_compensation_cents`, adjusts `compensation_committed_cents` by the delta between the new and old totals, and recomputes `requires_director_approval`. Re-tendering carries a `new_amount_cents`, moves `COUNTERED → TENDERED`, and performs the same amount overwrite, total recomputation, and committed-delta adjustment without consuming a round. The budget check applies to tender, counter, and re-tender alike — any of the three that would push committed funds past the budget is rejected with `ERR_COMPENSATION_EXCEEDS_BUDGET`. Operations that require the offer to be `TENDERED` or `COUNTERED` reject other states with `ERR_OFFER_NOT_TENDERED`.

Acceptance moves the offer from `TENDERED` or `COUNTERED` to `ACCEPTED`. When `requires_director_approval` is true, only a `DepartmentDirector` may accept — anyone else is rejected with `ERR_DIRECTOR_APPROVAL_REQUIRED` (403) — which is the second half of the segregation rule: the agent negotiates, the director approves large compensation. Acceptance leaves `compensation_committed_cents` unchanged, since the offer remains committed until the case closes, and it automatically creates a new `EasementDocument` of kind `DEED` in `DRAFT` for the acquired strip, ready for the title examiner's recording workflow of §3.2.

Every other exit releases money or refers the fight upward. A landowner's refusal moves the offer from `TENDERED` or `COUNTERED` to `REJECTED_BY_OWNER` and subtracts its `total_compensation_cents` from `compensation_committed_cents`. If the `negotiation_deadline` passes while the offer is `TENDERED` or `COUNTERED`, the system automatically moves it to `EXPIRED` with the same release. A `DepartmentDirector` may then refer an `EXPIRED` or `REJECTED_BY_OWNER` offer to condemnation, moving it to `CONDEMNATION_REFERRED` and auto-creating a litigation referral in `REFERRED` with `referral_reason` `CONDEMNATION`. Withdrawal from `DRAFT` releases nothing (nothing was committed) and from `TENDERED` releases the committed total, leaving the offer `WITHDRAWN` in both cases.

### 3.6. Vegetation Zones, Violations, and Exemption

Vegetation management is organized into zones on each case. A `VegetationInspector` creates a **Vegetation Zone** with a descriptive `zone_label`, the `max_allowed_height_ft` for vegetation, a `prohibited_species` list, and the geometry that drives the stricter wire-zone rule: `wire_zone_width_ft` and `border_zone_width_ft`. A new zone starts in `ACTIVE_MONITORING` with `violation_count` 0; the system-maintained `last_inspection_date` records when the zone was last inspected.

Recording a violation captures the `species`, the `observed_height_ft`, and the `location_within_zone` — `WIRE_ZONE` or `BORDER_ZONE`. The system then derives `excess_height_ft`. The applicable limit depends on where the growth stands: in the wire zone of a zone whose `wire_zone_width_ft` is greater than zero, the limit is half the zone's `max_allowed_height_ft`, because clearance directly beneath conductors is stricter; everywhere else the limit is the full `max_allowed_height_ft`. The excess is the observed height minus the applicable limit, floored at zero so compliant growth reads 0, and rounded half-up to 1 decimal place. A new violation starts in `DETECTED`, increments the zone's `violation_count`, and moves the zone automatically: the first violation pulls `ACTIVE_MONITORING → VIOLATION_DETECTED`, and once `violation_count` reaches the configured `VIOLATION_REMEDIATION_THRESHOLD` the zone escalates `VIOLATION_DETECTED → REMEDIATION_REQUIRED`, at which point every open violation in the zone has its `remediation_deadline` set or refreshed.

Notifying the owner moves a violation `DETECTED → NOTIFIED` and sets its `remediation_deadline` to the notification instant plus the configured `REMEDIATION_WINDOW_DAYS`. If that deadline passes unremediated, the system automatically escalates the violation `NOTIFIED → ESCALATED_TO_LEGAL` and auto-creates a `REFERRED` litigation referral with `referral_reason` `VEGETATION_REMEDIATION_FAILED`. Confirming the cleanup moves `NOTIFIED → REMEDIATED` and decrements the zone's `violation_count`; when the count falls back below `VIOLATION_REMEDIATION_THRESHOLD` a zone in `REMEDIATION_REQUIRED` relaxes to `VIOLATION_DETECTED`, and when the count reaches zero — from either of those zone states — the zone automatically becomes `CLEARED`. Acting on a violation after its `remediation_deadline` has passed is rejected with `ERR_DEADLINE_PASSED`.

Exemption is the `DepartmentDirector`'s safety valve, moving `DETECTED → EXEMPTED` and decrementing the zone count, but it is deliberately narrow: the observed `species` must not appear in the zone's `prohibited_species` list (else `ERR_PROHIBITED_SPECIES_NOT_EXEMPTABLE`), and the `excess_height_ft` must not exceed the configured `EXEMPTABLE_HEIGHT_MARGIN_FT` (else `ERR_EXCESS_HEIGHT_TOO_LARGE`). Prohibited species and large excesses are never exempted; they are remediated or litigated.

### 3.7. Litigation Referrals and Judicial Outcomes

When field remedies fail, the file moves to counsel. A **Litigation Referral** arises in two ways: automatically, as already described — a negotiation exhausted or an owner-response window missed creates one with `referral_reason` `NEGOTIATION_FAILED`, a remediation deadline missed creates one with `VEGETATION_REMEDIATION_FAILED`, and a condemnation referral creates one with `CONDEMNATION` — or manually, when a `RightOfWayAgent` creates a referral by naming the `encroachment_id` (which must belong to the same case, else `ERR_CROSS_CASE_REFERENCE`) and a `referral_reason` of `NEGOTIATION_FAILED`, `VEGETATION_REMEDIATION_FAILED`, `TITLE_DEFECT`, or `CONDEMNATION`. The system records the referring agent in `referred_by`, and every new referral starts in `REFERRED`.

Counsel's workflow is linear. Accepting a referral moves `REFERRED → ACCEPTED`, records the accepting counsel in `accepted_by`, and sets the `filing_deadline` to the acceptance instant plus the configured `FILING_WINDOW_DAYS`. Filing moves `ACCEPTED → FILED` and is rejected with `ERR_REFERRAL_NOT_ACCEPTED` when the referral has not been accepted. From `FILED`, the referral resolves in one of two ways, and both reject a referral that is not `FILED` with `ERR_REFERRAL_NOT_FILED`.

Settlement moves `FILED → SETTLED`, and its ripple depends on why the referral exists. For a `CONDEMNATION` referral, settlement finalizes the linked offer's compensation and clears the way for the case to proceed toward `CLOSED_CONDEMNED`. For a `NEGOTIATION_FAILED` referral, settlement moves the linked encroachment to `REMOVED` — a court-brokered removal. Recording a judgment moves `FILED → JUDGMENT_OBTAINED` with three parallel outcomes: a `NEGOTIATION_FAILED` referral removes the linked encroachment; a `VEGETATION_REMEDIATION_FAILED` referral marks the linked violation `REMEDIATED`; and a `CONDEMNATION` referral moves the case itself to `CLOSED_CONDEMNED`. A referral counsel declines to pursue is withdrawn, moving `REFERRED → WITHDRAWN`.

### 3.8. Closing the Case: Resolution, Condemnation, or Abandonment

Closure is a director-only act with a hard gate. Closing a resolved case moves `ACTIVE_MONITORING → CLOSED_RESOLVED`, and the gate is evaluated as the final step of the §2.8 pipeline: no encroachment may remain open, meaning `open_encroachment_count` must be zero (else `ERR_OPEN_ENCROACHMENTS_REMAIN`); no offer may remain in `DRAFT`, `TENDERED`, or `COUNTERED` (else `ERR_OPEN_OFFERS_EXIST`); no permit may remain `PENDING` (else `ERR_PENDING_PERMITS_EXIST`); and no referral may remain in `REFERRED` or `ACCEPTED` (else `ERR_PENDING_LITIGATION_EXISTS`). On closure every vegetation zone on the case is moved to `CLEARED`, and the compensation ledger is finalized: `compensation_balance_cents` is settled with accepted offers remaining committed and everything else released.

Condemnation is the adversarial closure, moving `RESOLUTION_PENDING → CLOSED_CONDEMNED`. It requires at least one offer already in `CONDEMNATION_REFERRED`, and it requires title work to be finished one way or the other — the latest title search must be `COMPLETED_CLEAN` or `COMPLETED_WITH_DEFECTS`. Condemning a case escalates every still-open encroachment to `ESCALATED_TO_LEGAL` and releases the committed compensation of every non-accepted offer back out of `compensation_committed_cents`. Recall from §3.7 that a `CONDEMNATION` referral ending in judgment likewise lands the case in `CLOSED_CONDEMNED`, and one ending in settlement leaves the case free to proceed there. Abandonment, described in §3.1, remains the third and simplest exit, available only from `INTAKE` and only while nothing has been recorded. All three closed states are terminal: once a case is in `CLOSED_RESOLVED`, `CLOSED_CONDEMNED`, or `CLOSED_ABANDONED`, no child may be created or transitioned beneath it.

## 4. Endpoint Definitions

Operations that create a new resource — a case, a document, an encroachment, an offer, a permit, a zone, a violation, a title search, or a referral — return `201 Created`. Operations that modify an existing resource, including all state-transition actions and the clock-advance capability, return `200 OK`. Query parameters marked optional in Section 3 (such as `status`, `county`, `doc_kind`, `severity_tier`, `approval_status`, and `permit_type`) act as filters on the corresponding list endpoints.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/easement-cases` | Create a new easement case | RightOfWayAgent |
| GET | `/easement-cases` | List easement cases | RightOfWayAgent, TitleExaminer, VegetationInspector, LitigationCounsel, DepartmentDirector |
| GET | `/easement-cases/{caseId}` | Get one easement case | RightOfWayAgent, TitleExaminer, VegetationInspector, LitigationCounsel, DepartmentDirector |
| POST | `/easement-cases/{caseId}/begin-mapping` | Transition case INTAKE → MAPPING | RightOfWayAgent |
| POST | `/easement-cases/{caseId}/activate-monitoring` | Transition case MAPPING → ACTIVE_MONITORING | RightOfWayAgent |
| POST | `/easement-cases/{caseId}/close-case` | Transition case ACTIVE_MONITORING → CLOSED_RESOLVED | DepartmentDirector |
| POST | `/easement-cases/{caseId}/condemn` | Transition case RESOLUTION_PENDING → CLOSED_CONDEMNED | DepartmentDirector |
| POST | `/easement-cases/{caseId}/abandon` | Transition case INTAKE → CLOSED_ABANDONED | DepartmentDirector |
| POST | `/easement-cases/{caseId}/documents` | Create an easement document (DRAFT) | TitleExaminer |
| GET | `/easement-cases/{caseId}/documents` | List documents for a case | RightOfWayAgent, TitleExaminer, LitigationCounsel, DepartmentDirector |
| GET | `/easement-cases/{caseId}/documents/{docId}` | Get one document | RightOfWayAgent, TitleExaminer, LitigationCounsel, DepartmentDirector |
| POST | `/easement-cases/{caseId}/documents/{docId}/record` | Record a DRAFT document | TitleExaminer |
| POST | `/easement-cases/{caseId}/documents/{docId}/reject-defective` | Reject a DRAFT document as defective | TitleExaminer |
| POST | `/easement-cases/{caseId}/encroachments` | Report a discovered encroachment | RightOfWayAgent |
| GET | `/easement-cases/{caseId}/encroachments` | List encroachments for a case | RightOfWayAgent, VegetationInspector, LitigationCounsel, DepartmentDirector |
| GET | `/easement-cases/{caseId}/encroachments/{encId}` | Get one encroachment | RightOfWayAgent, VegetationInspector, LitigationCounsel, DepartmentDirector |
| POST | `/easement-cases/{caseId}/encroachments/{encId}/notify` | Send encroachment notice (DISCOVERED → NOTIFIED) | RightOfWayAgent |
| POST | `/easement-cases/{caseId}/encroachments/{encId}/begin-negotiation` | Begin negotiation (NOTIFIED → NEGOTIATING) | RightOfWayAgent |
| POST | `/easement-cases/{caseId}/encroachments/{encId}/counter` | Record a counter-offer (NEGOTIATING → COUNTERED) | RightOfWayAgent |
| POST | `/easement-cases/{caseId}/encroachments/{encId}/resume-negotiation` | Resume after counter (COUNTERED → NEGOTIATING) | RightOfWayAgent |
| POST | `/easement-cases/{caseId}/encroachments/{encId}/agree-removal` | Reach removal agreement (NEGOTIATING or COUNTERED → REMOVAL_AGREED) | RightOfWayAgent |
| POST | `/easement-cases/{caseId}/encroachments/{encId}/confirm-removal` | Confirm removal (REMOVAL_AGREED → REMOVED) | RightOfWayAgent |
| POST | `/easement-cases/{caseId}/encroachments/{encId}/escalate` | Escalate to legal (NEGOTIATING or COUNTERED → ESCALATED_TO_LEGAL) | RightOfWayAgent |
| POST | `/easement-cases/{caseId}/encroachments/{encId}/waive` | Waive a MINOR encroachment | DepartmentDirector |
| POST | `/easement-cases/{caseId}/offers` | Create an acquisition offer (DRAFT) | RightOfWayAgent |
| GET | `/easement-cases/{caseId}/offers` | List offers for a case | RightOfWayAgent, DepartmentDirector, LitigationCounsel |
| GET | `/easement-cases/{caseId}/offers/{offerId}` | Get one offer | RightOfWayAgent, DepartmentDirector, LitigationCounsel |
| POST | `/easement-cases/{caseId}/offers/{offerId}/tender` | Tender an offer (DRAFT → TENDERED) | RightOfWayAgent |
| POST | `/easement-cases/{caseId}/offers/{offerId}/counter` | Counter an offer (TENDERED → COUNTERED) | RightOfWayAgent |
| POST | `/easement-cases/{caseId}/offers/{offerId}/re-tender` | Re-tender after counter (COUNTERED → TENDERED) | RightOfWayAgent |
| POST | `/easement-cases/{caseId}/offers/{offerId}/accept` | Accept an offer (TENDERED or COUNTERED → ACCEPTED) | RightOfWayAgent, DepartmentDirector |
| POST | `/easement-cases/{caseId}/offers/{offerId}/reject` | Mark offer rejected by owner | RightOfWayAgent |
| POST | `/easement-cases/{caseId}/offers/{offerId}/withdraw` | Withdraw an offer | RightOfWayAgent |
| POST | `/easement-cases/{caseId}/offers/{offerId}/refer-to-condemnation` | Refer an expired or rejected offer to condemnation | DepartmentDirector |
| POST | `/easement-cases/{caseId}/permits` | Request a third-party permit | RightOfWayAgent |
| GET | `/easement-cases/{caseId}/permits` | List permits for a case | RightOfWayAgent, VegetationInspector, DepartmentDirector |
| GET | `/easement-cases/{caseId}/permits/{permitId}` | Get one permit | RightOfWayAgent, VegetationInspector, DepartmentDirector |
| POST | `/easement-cases/{caseId}/permits/{permitId}/schedule-inspection` | Schedule field inspection | VegetationInspector |
| POST | `/easement-cases/{caseId}/permits/{permitId}/record-inspection` | Record inspection result | VegetationInspector |
| POST | `/easement-cases/{caseId}/permits/{permitId}/approve` | Approve a permit | RightOfWayAgent |
| POST | `/easement-cases/{caseId}/permits/{permitId}/deny` | Deny a permit | RightOfWayAgent |
| POST | `/easement-cases/{caseId}/permits/{permitId}/revoke` | Revoke an approved permit after failed inspection | DepartmentDirector |
| POST | `/easement-cases/{caseId}/vegetation-zones` | Create a vegetation zone | VegetationInspector |
| GET | `/easement-cases/{caseId}/vegetation-zones` | List vegetation zones | VegetationInspector, RightOfWayAgent, DepartmentDirector |
| GET | `/easement-cases/{caseId}/vegetation-zones/{zoneId}` | Get one zone | VegetationInspector, RightOfWayAgent, DepartmentDirector |
| POST | `/easement-cases/{caseId}/vegetation-zones/{zoneId}/violations` | Record a vegetation violation | VegetationInspector |
| GET | `/easement-cases/{caseId}/vegetation-zones/{zoneId}/violations` | List violations in a zone | VegetationInspector, RightOfWayAgent, DepartmentDirector |
| POST | `/easement-cases/{caseId}/vegetation-zones/{zoneId}/violations/{violId}/notify` | Notify owner of violation | VegetationInspector |
| POST | `/easement-cases/{caseId}/vegetation-zones/{zoneId}/violations/{violId}/confirm-remediation` | Confirm remediation | VegetationInspector |
| POST | `/easement-cases/{caseId}/vegetation-zones/{zoneId}/violations/{violId}/exempt` | Exempt a violation | DepartmentDirector |
| POST | `/easement-cases/{caseId}/title-searches` | Order a title search | TitleExaminer |
| GET | `/easement-cases/{caseId}/title-searches` | List title searches for a case | TitleExaminer, RightOfWayAgent, DepartmentDirector |
| GET | `/easement-cases/{caseId}/title-searches/{taskId}` | Get one title search | TitleExaminer, RightOfWayAgent, DepartmentDirector |
| POST | `/easement-cases/{caseId}/title-searches/{taskId}/begin` | Begin title search | TitleExaminer |
| POST | `/easement-cases/{caseId}/title-searches/{taskId}/complete` | Complete title search | TitleExaminer |
| POST | `/easement-cases/{caseId}/title-searches/{taskId}/cancel` | Cancel a title search | TitleExaminer |
| POST | `/easement-cases/{caseId}/litigation-referrals` | Manually refer to litigation | RightOfWayAgent |
| GET | `/easement-cases/{caseId}/litigation-referrals` | List litigation referrals | LitigationCounsel, RightOfWayAgent, DepartmentDirector |
| GET | `/easement-cases/{caseId}/litigation-referrals/{refId}` | Get one referral | LitigationCounsel, RightOfWayAgent, DepartmentDirector |
| POST | `/easement-cases/{caseId}/litigation-referrals/{refId}/accept` | Accept a referral | LitigationCounsel |
| POST | `/easement-cases/{caseId}/litigation-referrals/{refId}/file` | Mark case filed | LitigationCounsel |
| POST | `/easement-cases/{caseId}/litigation-referrals/{refId}/settle` | Record settlement | LitigationCounsel |
| POST | `/easement-cases/{caseId}/litigation-referrals/{refId}/record-judgment` | Record a judgment | LitigationCounsel |
| POST | `/easement-cases/{caseId}/litigation-referrals/{refId}/withdraw` | Withdraw a referral | LitigationCounsel |
| GET | `/easement-cases/documents/{docId}` | Flat get of a document by id | RightOfWayAgent, TitleExaminer, LitigationCounsel, DepartmentDirector |
| GET | `/easement-cases/documents` | Flat filtered list of documents | RightOfWayAgent, TitleExaminer, LitigationCounsel, DepartmentDirector |
| GET | `/easement-cases/encroachments/{encId}` | Flat get of an encroachment by id | RightOfWayAgent, VegetationInspector, LitigationCounsel, DepartmentDirector |
| GET | `/easement-cases/encroachments` | Flat filtered list of encroachments | RightOfWayAgent, VegetationInspector, LitigationCounsel, DepartmentDirector |
| GET | `/easement-cases/offers/{offerId}` | Flat get of an offer by id | RightOfWayAgent, DepartmentDirector, LitigationCounsel |
| GET | `/easement-cases/offers` | Flat filtered list of offers | RightOfWayAgent, DepartmentDirector, LitigationCounsel |
| GET | `/easement-cases/permits/{permitId}` | Flat get of a permit by id | RightOfWayAgent, VegetationInspector, DepartmentDirector |
| GET | `/easement-cases/permits` | Flat filtered list of permits | RightOfWayAgent, VegetationInspector, DepartmentDirector |
| GET | `/easement-cases/vegetation-zones/{zoneId}` | Flat get of a zone by id | VegetationInspector, RightOfWayAgent, DepartmentDirector |
| GET | `/easement-cases/vegetation-zones` | Flat filtered list of zones | VegetationInspector, RightOfWayAgent, DepartmentDirector |
| GET | `/easement-cases/violations/{violId}` | Flat get of a violation by id | VegetationInspector, RightOfWayAgent, DepartmentDirector |
| GET | `/easement-cases/violations` | Flat filtered list of violations | VegetationInspector, RightOfWayAgent, DepartmentDirector |
| GET | `/easement-cases/title-searches/{taskId}` | Flat get of a title search by id | TitleExaminer, RightOfWayAgent, DepartmentDirector |
| GET | `/easement-cases/title-searches` | Flat filtered list of title searches | TitleExaminer, RightOfWayAgent, DepartmentDirector |
| GET | `/easement-cases/litigation-referrals/{refId}` | Flat get of a referral by id | LitigationCounsel, RightOfWayAgent, DepartmentDirector |
| GET | `/easement-cases/litigation-referrals` | Flat filtered list of referrals | LitigationCounsel, RightOfWayAgent, DepartmentDirector |
| POST | `/_clock/set_current_utc` | Set the logical clock | RightOfWayAgent, TitleExaminer, VegetationInspector, LitigationCounsel, DepartmentDirector |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of Sections 2 and 3; this catalogue lists only identifiers and status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_ROLE` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NEGOTIATOR_CANNOT_APPROVE_OWN_OFFER` | 403 Forbidden |
| `ERR_DIRECTOR_APPROVAL_REQUIRED` | 403 Forbidden |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_DOCUMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ENCROACHMENT_NOT_FOUND` | 404 Not Found |
| `ERR_OFFER_NOT_FOUND` | 404 Not Found |
| `ERR_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_ZONE_NOT_FOUND` | 404 Not Found |
| `ERR_VIOLATION_NOT_FOUND` | 404 Not Found |
| `ERR_TITLE_TASK_NOT_FOUND` | 404 Not Found |
| `ERR_REFERRAL_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_OPEN_FOR_RECORDING` | 409 Conflict |
| `ERR_CASE_NOT_MONITORING` | 409 Conflict |
| `ERR_CASE_ALREADY_CLOSED` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_OFFER_NOT_TENDERED` | 409 Conflict |
| `ERR_ENCROACHMENT_NOT_NEGOTIATING` | 409 Conflict |
| `ERR_PERMIT_NOT_PENDING` | 409 Conflict |
| `ERR_TASK_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_DOCUMENT_NOT_DRAFT` | 409 Conflict |
| `ERR_REFERRAL_NOT_ACCEPTED` | 409 Conflict |
| `ERR_REFERRAL_NOT_FILED` | 409 Conflict |
| `ERR_INSPECTION_NOT_PASSED` | 409 Conflict |
| `ERR_ONLY_FAILED_INSPECTION_REVOKABLE` | 409 Conflict |
| `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` | 409 Conflict |
| `ERR_NEGOTIATION_ROUNDS_NOT_EXHAUSTED` | 409 Conflict |
| `ERR_OPEN_ENCROACHMENTS_REMAIN` | 409 Conflict |
| `ERR_OPEN_OFFERS_EXIST` | 409 Conflict |
| `ERR_PENDING_PERMITS_EXIST` | 409 Conflict |
| `ERR_PENDING_LITIGATION_EXISTS` | 409 Conflict |
| `ERR_NO_DOCUMENTS_ON_CASE` | 409 Conflict |
| `ERR_NO_RECORDED_DOCUMENT` | 409 Conflict |
| `ERR_RECORDED_DOCUMENT_EXISTS` | 409 Conflict |
| `ERR_ONLY_MINOR_WAIVABLE` | 409 Conflict |
| `ERR_CROSS_CASE_REFERENCE` | 409 Conflict |
| `ERR_TITLE_NOT_CLEARED` | 409 Conflict |
| `ERR_TITLE_DEFECTS_EXIST` | 409 Conflict |
| `ERR_DUPLICATE_INSTRUMENT_NUMBER` | 409 Conflict |
| `ERR_DOCUMENT_NOT_RECORDED` | 409 Conflict |
| `ERR_SELF_SUPERSEDE` | 409 Conflict |
| `ERR_INVALID_DATE_RANGE` | 422 Unprocessable Entity |
| `ERR_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_PERMIT_OVERLAP` | 409 Conflict |
| `ERR_INSURANCE_REQUIRED` | 409 Conflict |
| `ERR_PROHIBITED_SPECIES_NOT_EXEMPTABLE` | 409 Conflict |
| `ERR_EXCESS_HEIGHT_TOO_LARGE` | 409 Conflict |
| `ERR_COMPENSATION_EXCEEDS_BUDGET` | 402 Payment Required |
| `ERR_STALE_CASE_VERSION` | 412 Precondition Failed |

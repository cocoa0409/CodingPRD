# Underground Damage Recovery API — Product Requirements Document

## 1. Introduction

Underground utility strikes during excavation are among the most preventable — and most expensive — classes of infrastructure incidents in North America. When a backhoe severs a gas lateral or a directional bore nicks a fiber trunk, the resulting workflow is a mess of paper: a damage report at the intake desk, a pile of photographs, an 811 ticket pulled from a separate system, a locator's markings that may or may not have been on time, and then months of back-and-forth over who owes what. The Damage Prevention & Underground Damage Claim Recovery service is the utility's recovery unit made programmatic. It takes a damage case from the moment a strike is reported all the way through documentation, root-cause analysis, fault allocation among excavator / locator / facility owner, repair-cost compilation, invoicing, payment, dispute, subrogation, and regulatory filing — with a repeat-offender program and prevention-training layer sitting on top to push chronic offenders back into compliance.

This document is the authoritative functional specification for the REST API. It is written for the engineer implementing the service and the auditor reviewing it. Two design commitments shape everything below. First, the unit operates under segregation of duties: the person who investigates a case is never the person who finalizes its fault allocation, and the person who proposes shares is never the person who approves them. Second, every monetary flow is conservative and auditable: cost lines are pinned per line with a fixed rounding order, invoice totals conserve exactly to the case subtotal, payment waterfalls absorb remainders into a customer credit balance, and subrogation recoveries split deterministically among legal costs, invoice balance, and the utility's general fund. The result is a system that can be audited line-by-line years later and still reconcile to the cent.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. Both must be present and the role must be one of the declared role names below; otherwise the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the caller's role is not listed in the endpoint's authorized role list, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The declared roles are exactly:

- `IntakeCoordinator` — the damage-report intake desk. Creates damage cases, adds scene evidence, links tickets.
- `DamageInvestigator` — the field investigator. Claims investigations, reconstructs timelines, audits locate responses, drafts / proposes / revises fault allocations.
- `ClaimsAdjuster` — the recovery adjuster. Compiles repair costs, issues invoices, responds to disputes, files regulatory reports.
- `RecoveryManager` — the unit manager. Registers excavators / locators / courses, suspends locators, evaluates the repeat-offender program, finalizes allocations, writes off invoices, reverses payments, settles and closes subrogation cases, closes damage cases, overturns violations, drives the test clock.
- `Excavator` — an excavating-contractor user.
- `Locator` — a locating-contractor user.
- `System` — an internal automation actor for clock sweeps and cascade transitions; never callable via an API role header.

Two of the roles are entity-backed; the rest are opaque operator identifiers.

- When `X-User-Role` is `Excavator`, `X-User-ID` is the `id` of the acting `Excavator`; ownership checks on any resource that references an `Excavator` compare the resource's foreign-key field (for example `excavator_id` on a `LocateTicket`, `TrainingAssignment`, or `DamageCase`) to `X-User-ID`. Mismatches are rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).
- When `X-User-Role` is `Locator`, `X-User-ID` is the `id` of the acting `Locator`; ownership checks on any resource that references a `Locator` (for example `locator_id` on a `LocateResponse`, or the contest-party membership on a `FaultAllocation`'s shares) compare to `X-User-ID`. Mismatches are rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).
- When `X-User-Role` is `IntakeCoordinator`, `DamageInvestigator`, `ClaimsAdjuster`, or `RecoveryManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example as `investigator_user_id` on a `DamageCase` when begin-investigation succeeds, or as `filed_by_id` on a `Dispute`) but does not compare it to any entity's `id` for ownership purposes.

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

All list endpoints accept two query parameters: `limit` and `offset`. `limit` defaults to 10, must be at least 1, and is capped at 100. `offset` defaults to 0 and must be non-negative. List endpoints sort by `created_at` ascending. The response `meta` block for a list endpoint includes `limit`, `offset`, `total_count`, and `has_more` in addition to the two request identifiers.

### 2.4. Common Resource Properties

Every persisted entity except `EvidenceItem` and `TimelineEvent` carries four system-managed fields: `id` (a server-minted UUID with no type prefix), `created_at` (ISO 8601 UTC with three fractional digits), `updated_at` (same format, refreshed on every mutation), and `version` (an integer starting at 1 and incremented by 1 on every mutation of the entity). `EvidenceItem` and `TimelineEvent` carry only `id` and `created_at`; both `updated_at` and `version` are absent on those two entities and are not present in their payloads.

Two entities also mint human-facing reference numbers on creation: a `LocateTicket` carries a server-minted `ticket_number` of the form `TCK-<seq>`, and a `DamageCase` carries a server-minted `case_number` of the form `DC-<seq>`.

### 2.5. The Logical Clock and the Expiry Sweep

The service does not read wall-clock time for business logic. All temporal decisions (window checks, deadline computation, decay buckets, expiry sweeps) read a logical clock that is set explicitly via a manager-only test-driving capability. The clock-set request body carries a single field `to_iso8601` holding the target instant. The startup default, before any call to set the clock, is exactly `2026-05-01T00:00:00Z`. Setting the clock to a supplied `to` instant also triggers an expiry sweep: any `OPEN` `LocateTicket` whose `work_end_at` has passed moves to `EXPIRED`; any `OPEN` `Dispute` whose `response_deadline_at` has passed moves to `EXPIRED`; any `ASSIGNED` `TrainingAssignment` whose `due_at` has passed moves to `EXPIRED`.

### 2.6. Hierarchical Consistency, Cascades, and Derived Totals

When one operation mutates more than one entity, every cascade is explicit. A first `EvidenceItem` on a `DamageCase` flips the case's investigation dimension from `REPORTED` to `DOCUMENTING`, increments the case's `evidence_count`, and bumps its `version`. A first `CostLineItem` flips the recovery dimension from `UNBILLED` to `COSTING`, recomputes the case's `subtotal_cents`, and bumps the case's `version`. A first `LocateResponse` on a ticket flips the ticket from `OPEN` to `COMPLETED` and bumps the ticket's `version`. A finalize of a fault allocation drives a transitive cascade described in §3.4. A payment landing on an invoice flips the case's recovery dimension from `INVOICED` to `COLLECTING`, and a payment reversal that reopens a terminal invoice flips `RECOVERED` back to `COLLECTING`.

Derived aggregates are recomputed, not maintained incrementally by callers. `DamageCase.subtotal_cents` is the sum of `line_total_cents` over non-deleted `CostLineItem` rows; `DamageCase.total_invoiced_cents` is the sum of `invoiced_cents` over the case's `ClaimInvoice` rows; `DamageCase.total_recovered_cents` is the sum of `amount_paid_cents` over the case's `ClaimInvoice` rows; `DamageCase.evidence_count` is the count of `EvidenceItem` rows for the case. `ClaimInvoice.amount_paid_cents` is the sum of `APPLIED` `Payment` allocation legs targeting the invoice minus reversed legs. `ClaimInvoice.amount_due_cents` is `invoiced_cents` minus `amount_paid_cents`; a successful write-off then sets it to 0 (§3.5). `Excavator.total_outstanding_cents` is the sum of `amount_due_cents` over that excavator's invoices in `ISSUED`, `PARTIALLY_PAID`, or `DISPUTED`. `Locator.total_responses` is set at response creation; `Locator.performance_score_bp` is recomputed on every audit.

### 2.7. Nested Resource Retrieval and Identifier Resolution

Every id appearing in a URL path or in a request body — `damage_case_id`, `locate_ticket_id`, `locator_id`, `excavator_id`, `course_id`, `fault_allocation_id`, `claim_invoice_id`, `dispute_id`, `payer_id`, `target_id`, each `party_id` inside a `shares` entry, `amends_report_id`, `supersedes_allocation_id` — must resolve to an existing record; otherwise the request is rejected with `ERR_NOT_FOUND` (HTTP 404). Path parameters are validated left to right: each identifier in a nested path is resolved in turn before any deeper segment is considered.

### 2.8. Precision, Rounding, and Integer Cents

All monetary values are integer cents. The rounding rule across the entire system is **round half up**, applied at precisely one point in each calculation — never compounded across intermediate steps. Per-line totals round once at the final multiply of `repair_cost_compilation`; per-invoice allocation rounds once at the share multiply of `allocation_distribution`; per-line allocation of a rounded total is forbidden because it would drift cents. The legal-time precision is whole days and whole basis points; a basis point is one hundredth of a percent, and a fault allocation's shares sum to exactly 10000 basis points (100.00%).

### 2.9. Optimistic Concurrency Control

Exactly one endpoint participates in optimistic concurrency control: creating a `FaultAllocation` requires the request body to carry `expected_damage_case_version`, holding the client's last-observed `version` of the target `DamageCase`. If the value does not match the case's current `version` — because another writer has advanced the case since the client last read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The rule exists because creating an allocation legitimately supersedes the case's prior non-`FINAL` allocation and bumps the case's `version`; a writer holding a stale case `version` must re-observe before superseding. No other endpoint takes an `expected_*_version` field.

### 2.10. Segregation of Duties

The unit enforces a hard segregation between investigation and finalization. When a `DamageInvestigator` claims a case via begin-investigation, the server records that caller's `X-User-ID` on the case as `investigator_user_id`. The subsequent finalize of any fault allocation on that case must come from a `RecoveryManager` whose `X-User-ID` is different from the recorded `investigator_user_id`; if the two identifiers are equal, the finalize is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.11. Repeat-Offender Program Bands

Each `Excavator` carries a `program_status` drawn from exactly `GOOD_STANDING`, `WATCH`, `PROBATION`, `SUSPENDED`. The band is driven by a decay-adjusted points score described in §3.7: points at or above 18 yield `SUSPENDED`, at or above 12 yield `PROBATION`, at or above 6 yield `WATCH`, otherwise `GOOD_STANDING`. The boundaries are inclusive. Upgrades to a worse band are free (they apply on every evaluation); downgrades to a better band are gated by completion of remediation training — leaving `PROBATION` or `SUSPENDED` requires every `TrainingAssignment` whose course's `required_for_status` matches the current band to be `COMPLETED`, otherwise the band holds without error.

### 2.12. Logical-Clock Sweeps

Three sweep rules run when the logical clock advances: `OPEN` locate tickets whose `work_end_at` has passed become `EXPIRED`; `OPEN` disputes whose `response_deadline_at` has passed become `EXPIRED`; and `ASSIGNED` training assignments whose `due_at` has passed become `EXPIRED`. The sweeps are atomic with the clock set and run before the response to the clock-set call is returned.

## 3. Business Logic & Workflows

### 3.1. Registration and Party Setup

A `RecoveryManager` registers the two contractor kinds. Creating an `Excavator` requires `company_name` and `contact_email`; the new row is initialized with `program_status` `GOOD_STANDING`, `offender_points` 0, `credit_balance_cents` 0, and `total_outstanding_cents` 0. Creating a `Locator` requires `company_name`, `contact_email`, and `contract_region`; the new row is initialized with `contract_status` `ACTIVE`, `performance_score_bp` 10000 (the value when no audits exist yet), and `total_responses` 0. A manager may also suspend a locator, moving `contract_status` from `ACTIVE` to `SUSPENDED`; a suspended locator cannot submit marking responses (the submission is rejected with `ERR_LOCATOR_INACTIVE`, HTTP 409). The same manager registers `TrainingCourse` rows by supplying a `course_code`, `title`, `required_for_status` (one of `WATCH`, `PROBATION`, `SUSPENDED`), and `credit_hours` greater than zero; `course_code` is a natural key unique across all courses, and reuse is rejected with `ERR_DUPLICATE_COURSE_CODE` (HTTP 409).

### 3.2. The 811 Ticket and the Locate Response

Before breaking ground, an `Excavator` files a locate ticket carrying `excavator_id`, `dig_site_address`, `work_start_at`, and `work_end_at`. The dig window is the half-open interval `[work_start_at, work_end_at)` — the start is inclusive, the end is exclusive — and `work_end_at` must be strictly after `work_start_at` (otherwise `ERR_TICKET_WINDOW_INVALID`, HTTP 422). Two `OPEN` tickets for the same `(excavator_id, dig_site_address)` pair must not overlap; an overlapping window is rejected with `ERR_TICKET_WINDOW_CONFLICT` (HTTP 409), while two windows that merely touch at a boundary are permitted. The caller's `X-User-ID` must equal the supplied `excavator_id` (otherwise `ERR_OWNERSHIP_MISMATCH`). A ticket filed by a `SUSPENDED` excavator is rejected with `ERR_PROGRAM_SUSPENDED` (HTTP 409). A successful create initializes `status` to `OPEN`, `renewal_count` to 0, and mints a `ticket_number`.

The excavator may renew an `OPEN` ticket by supplying a `new_work_end_at`; the renewal extends `work_end_at`, increments `renewal_count`, and bumps `version`. Renewing requires the new end to be strictly after the current `work_end_at` (otherwise `ERR_TICKET_WINDOW_INVALID`) and must not produce an overlap with another `OPEN` ticket of the same `(excavator_id, dig_site_address)` (otherwise `ERR_TICKET_WINDOW_CONFLICT`). Renewing a ticket that has already moved out of `OPEN` is rejected with `ERR_INVALID_STATE` (HTTP 409). Renewals are reflected only in the ticket fields; they are not reconstructed as timeline events later.

A `DamageInvestigator` audits a response by supplying a `verdict` of `ACCURATE` or `INACCURATE`; auditing a response whose `accuracy_verdict` is no longer `UNAUDITED` is rejected with `ERR_INVALID_STATE`. On success the response's `accuracy_verdict` is set to the supplied `verdict` and the locator's `performance_score_bp` is recomputed.

A `Locator` submits a `LocateResponse` against a ticket by supplying `locate_ticket_id`, `locator_id`, `response_code` (one of `MARKED`, `CLEAR`, `PARTIAL`), `marks_completed_at`, and optionally `notes` (defaulting to an empty string when omitted). The caller's `X-User-ID` must equal `locator_id`. Submitting against a ticket whose `status` is `EXPIRED` is rejected with `ERR_TICKET_EXPIRED` (HTTP 409); submitting while the locator's `contract_status` is `SUSPENDED` is rejected with `ERR_LOCATOR_INACTIVE`. On success the new response's `accuracy_verdict` is `UNAUDITED`, the ticket moves from `OPEN` to `COMPLETED` with its `version` bumped, and the locator's `total_responses` increments by 1.

### 3.3. Damage Intake and Scene Documentation

When a strike occurs, an `IntakeCoordinator` intakes a `DamageCase` by supplying `excavator_id`, `dig_site_address`, `facility_type` (one of `GAS`, `ELECTRIC`, `TELECOM`, `WATER`), `severity` (one of `MINOR`, `MAJOR`, `CRITICAL`), `occurred_at`, and optionally `locate_ticket_id`. The new case is initialized with `investigation_status` `REPORTED`, `recovery_status` `UNBILLED`, all computed totals at 0, an empty `reconstruction_flags` array, and a server-minted `case_number`.

Scene documentation is added by either an `IntakeCoordinator` or a `DamageInvestigator`. Each `EvidenceItem` carries `damage_case_id`, `evidence_type` (one of `PHOTO`, `MEASUREMENT`, `WITNESS_STATEMENT`, `SKETCH`), `captured_at`, and `description`. The temporal admissibility rule is strict: `captured_at` must not be later than seventy-two hours after the case's `occurred_at` — evidence captured past that window is rejected with `ERR_EVIDENCE_INADMISSIBLE` (HTTP 422). Adding evidence to a case that is already `CLOSED` is rejected with `ERR_INVALID_STATE`. The first evidence item created for a case moves the case's `investigation_status` from `REPORTED` to `DOCUMENTING`, increments `evidence_count`, and bumps the case's `version`; subsequent items also increment `evidence_count` and bump `version` without further dimension changes.

A ticket may be linked after the fact by either the intake coordinator or the investigator. The link requires the target ticket's `status` to be `COMPLETED` (otherwise `ERR_INVALID_STATE`) and requires the case's `occurred_at` to fall within the ticket's half-open dig window `[work_start_at, work_end_at)` (otherwise `ERR_DAMAGE_OUTSIDE_TICKET_WINDOW`, HTTP 409). A successful link sets `locate_ticket_id` on the case and bumps the case's `version`.

### 3.4. Investigation, Timeline Reconstruction, and the Fault Allocation Cycle

A `DamageInvestigator` claims a case by invoking begin-investigation. The case's `investigation_status` must be `REPORTED` or `DOCUMENTING` (otherwise `ERR_INVALID_STATE`); on success the dimension moves to `INVESTIGATING`, the case records `investigator_user_id` from the caller's `X-User-ID`, and the case's `version` bumps. This `investigator_user_id` is the segregation-of-duties anchor used at finalize time (§2.10).

Timeline reconstruction is the investigator's tool for reconstructing what happened when. Invoking it first deletes any prior `TimelineEvent` rows for the case, then rebuilds from the linked ticket (if any), every `LocateResponse` against that ticket, every `EvidenceItem` for the case, and the case itself. Each source produces one event with an `event_kind` of `TICKET_SUBMITTED`, `RESPONSE_SUBMITTED`, `EVIDENCE_CAPTURED`, or `DAMAGE_OCCURRED`, a `source_ref_id` pointing at the source record, an `event_at` taken from the source (`created_at` for the ticket, `marks_completed_at` for a response, `captured_at` for evidence, `occurred_at` for the case), and a `flag` that is `NONE` unless one of the anomaly rules below fires. Events sort by `event_at` ascending; ties break by the source record's `created_at` ascending; further ties break by `event_kind` in the order `TICKET_SUBMITTED` before `RESPONSE_SUBMITTED` before `EVIDENCE_CAPTURED` before `DAMAGE_OCCURRED`. Four anomaly flags exist, all computed in UTC: a `RESPONSE_SUBMITTED` event whose `event_at` is strictly later than the ticket's `work_start_at` is flagged `LATE_MARK`; a `RESPONSE_SUBMITTED` event whose `event_at` is strictly earlier than fourteen days before the case's `occurred_at` is flagged `STALE_MARKS`; a `RESPONSE_SUBMITTED` event whose `event_at` is strictly later than the case's `occurred_at` is flagged `POST_DAMAGE_MARK`. When the case has no linked ticket at all, the case-level flag `NO_TICKET` is added without producing an event. The union of all fired flags is written onto the case's `reconstruction_flags`. Invoking reconstruction when the case has neither a linked ticket, nor any responses, nor any evidence is rejected with `ERR_TIMELINE_EMPTY` (HTTP 409).

Fault allocation is the heart of the recovery. A `DamageInvestigator` creates a `FaultAllocation` against a case by supplying `damage_case_id`, a `root_cause_code` drawn from `NO_TICKET`, `EXPIRED_TICKET`, `MISMARK`, `LOCATE_LATE`, `OWNER_ABANDONED`, and the OCC field `expected_damage_case_version` (§2.9). Optionally the investigator may supply `shares`, an array of entries each carrying a `party_type` (`EXCAVATOR`, `LOCATOR`, or `FACILITY_OWNER`), a `party_id` (a string id or `null`), and a `share_bp` integer; when supplied, the `share_bp` values must sum to exactly 10000 (otherwise `ERR_SHARES_MUST_SUM_10000`, HTTP 422). When `shares` is omitted, the server fills them from the rule-default table below and records `basis` as `RULE_DEFAULT`; when supplied, the server takes them verbatim and records `basis` as `ADJUDICATED`. The rule-default table maps each `root_cause_code` to a fixed share distribution: `NO_TICKET` assigns the full 10000 to the excavator; `EXPIRED_TICKET` assigns 8000 to the excavator and 2000 to the facility owner; `MISMARK` assigns 7000 to the locator and 3000 to the excavator; `LOCATE_LATE` assigns 6000 to the locator and 4000 to the excavator; `OWNER_ABANDONED` assigns the full 10000 to the facility owner. For the excavator entry the `party_id` is the case's `excavator_id`; for the locator entry the `party_id` is the `locator_id` of the earliest-created `LocateResponse` on the case's linked ticket, or `null` when there is none; for the facility owner entry the `party_id` is `null`. The create requires the case's `investigation_status` to be `INVESTIGATING` (otherwise `ERR_INVALID_STATE`). On success the new allocation starts in `DRAFT` with `revision_no` 0; any prior allocation of the same case that is not yet `FINAL` moves to `SUPERSEDED`, and the new allocation's `supersedes_allocation_id` is set to the superseded allocation's id. The create also bumps the parent case's `version` by 1.

The allocation then walks a cyclic negotiation. Proposing a `DRAFT` allocation requires the case's `investigation_status` to be `INVESTIGATING`; on success the allocation moves to `PROPOSED`, `proposed_at` is set to the current logical clock, `contest_deadline_at` is computed as ten days after `proposed_at`, the case's `investigation_status` moves to `FAULT_PROPOSED`, and the case's `version` bumps. Once `PROPOSED`, a named party (an `Excavator` or `Locator` whose `X-User-ID` appears as a `party_id` on the allocation's `shares`) or a `RecoveryManager` may contest the allocation; the manager is exempt from the party-membership check. Contesting from any status other than `PROPOSED` is rejected with `ERR_INVALID_STATE` — the state check is evaluated before the temporal check — and contesting after `contest_deadline_at` has passed is rejected with `ERR_CONTEST_WINDOW_CLOSED` (HTTP 409). A non-manager caller whose `X-User-ID` is not among the shares' `party_id` values is rejected with `ERR_OWNERSHIP_MISMATCH`. A successful contest moves the allocation to `CONTESTED`, optionally carrying a `contest_note`, and bumps the allocation's `version`.

A contested allocation cycles back through revision. The investigator invokes revise on a `CONTESTED` allocation, optionally supplying a new `root_cause_code` and a new `shares` array; when `shares` is supplied in revise, it replaces the existing array and must still sum to exactly 10000 (otherwise `ERR_SHARES_MUST_SUM_10000`). Revision moves the allocation back to `DRAFT`, increments `revision_no` by 1, clears `proposed_at` and `contest_deadline_at` to null, returns the case's `investigation_status` to `INVESTIGATING`, and bumps both the case's and the allocation's `version`. The cycle `PROPOSED → CONTESTED → DRAFT → PROPOSED` may repeat any number of times.

Finalization is the manager's act and triggers the deepest cascade in the system. A `RecoveryManager` finalizes a `PROPOSED` allocation, optionally passing `override_authority_cap` as a boolean. Three precondition checks apply in addition to the state check: the caller's `X-User-ID` must differ from the case's `investigator_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`); the case's `evidence_count` must be at least 1 (otherwise `ERR_NO_SCENE_EVIDENCE`, HTTP 409); and the case's `subtotal_cents` must not exceed 5000000 cents (fifty thousand dollars) unless `override_authority_cap` is passed as true (otherwise `ERR_INVOICE_AUTHORITY_CAP_EXCEEDED`, HTTP 409). On success the allocation moves to `FINAL`; the case's `investigation_status` moves to `FAULT_FINAL`; the case's `recovery_status` moves to `INVOICED`; one `ClaimInvoice` in `DRAFT` is created per share with `share_bp` strictly greater than zero via the allocation-distribution rule (§3.5); and if the excavator's `share_bp` is at least 5000, a `ViolationRecord` is created against the case's `excavator_id` with points derived from the case's `severity` (2 for `MINOR`, 4 for `MAJOR`, 6 for `CRITICAL`). The violation creation triggers a recompute of the excavator's repeat-offender score (§3.7); the new band applies immediately if it is worse than the current band, and entering `PROBATION` or `SUSPENDED` from a better band auto-creates one `TrainingAssignment` per matching course. Both the case and the allocation have their `version` bumped.

### 3.5. Repair Costs and Invoicing

A `ClaimsAdjuster` adds repair cost lines to a case. Each `CostLineItem` carries `damage_case_id`, `category` (one of `LABOR`, `MATERIAL`, `EQUIPMENT`, `RESTORATION`), `description`, `quantity` greater than zero, and `unit_cost_cents` greater than zero. Adding a line to a case that is `CLOSED` or already at `INVOICED` or later in its recovery dimension is rejected with `ERR_INVALID_STATE`. The first line created on a case moves the case's recovery dimension from `UNBILLED` to `COSTING`, recomputes `subtotal_cents`, and bumps the case's `version`.

Each line's `line_total_cents` is computed server-side. A category-specific markup is applied to the submitted unit cost: 15% for `LABOR`, 10% for `MATERIAL`, 12% for `EQUIPMENT`, 8% for `RESTORATION`. If the case's `severity` is `CRITICAL`, an emergency multiplier of 1.25 also applies; otherwise the multiplier is 1.00. The raw line amount is the quantity multiplied by the unit cost, then multiplied by one-plus-the-markup, then multiplied by the emergency multiplier; the result is rounded half-up to a whole cent exactly once, at this final multiply; and the line total is capped at 500000 cents (five thousand dollars) per line — if the rounded value exceeds the cap, the line total is the cap. The per-line rounding happens before any case-level sum, so `subtotal_cents` is always the sum of already-rounded line totals. A line may be removed only while the case's `recovery_status` is `COSTING` (otherwise `ERR_INVALID_STATE`); deletion recomputes `subtotal_cents` and bumps the case's `version`.

When a fault allocation finalizes, the server creates one `ClaimInvoice` per share with `share_bp` strictly greater than zero. The split rule is a remainder-absorbing waterfall. The largest share (highest `share_bp`; ties broken by lowest index in the allocation's `shares` array) is designated the residual recipient. For every non-largest share, the invoiced amount is the case's `subtotal_cents` multiplied by that share's `share_bp`, divided by 10000, rounded half-up to a whole cent. The largest share's invoiced amount is the case's `subtotal_cents` minus the sum of the other invoices' amounts — this absorbs any remainder so that the sum of `invoiced_cents` across all created invoices equals the case's `subtotal_cents` exactly. Each invoice's `debtor_type` is the share's `party_type`, and its `debtor_id` is the share's `party_id` — except when `party_type` is `FACILITY_OWNER`, in which case `debtor_id` is the literal string `FACILITY_OWNER`. Each invoice is created in `DRAFT` with `invoiced_cents` set as just described and `amount_paid_cents` initialized to 0; `amount_due_cents` is the difference. Each invoice also carries a `standard_basis_cents` field computed alongside the actual basis for audit comparison: the same quantities priced at standard unit rates (9500 cents for `LABOR`, 4000 cents for `MATERIAL`, 15000 cents for `EQUIPMENT`, 6000 cents for `RESTORATION`) with the same category markups, the same emergency multiplier, and the same per-line cap, then allocated by the same share-and-remainder rule. The actual basis uses the submitted `unit_cost_cents` and is the amount actually billed; the standard basis substitutes the standard rates and is surfaced only for comparison — identical inputs produce a different total whenever any submitted unit cost differs from the standard rate. The case's `total_invoiced_cents` is the sum of `invoiced_cents` over its invoices.

A `ClaimsAdjuster` issues a `DRAFT` invoice, moving its `status` to `ISSUED`, setting `issued_at` to the current logical clock, computing `due_at` as thirty days after `issued_at`, and recomputing the debtor's `total_outstanding_cents`. A `RecoveryManager` may write off an invoice in `ISSUED` or `PARTIALLY_PAID`, provided two conditions hold: no `Dispute` on that invoice is in `OPEN`, `UNDER_REVIEW`, or `COUNTERED` (otherwise `ERR_INVOICE_HAS_OPEN_DISPUTE`, HTTP 409); and the invoice's `amount_due_cents` is at most 20000 cents (two hundred dollars) (otherwise `ERR_WRITE_OFF_CAP_EXCEEDED`, HTTP 409). A successful write-off moves the invoice to `WRITTEN_OFF`, forgives the remaining `amount_due_cents` — the invoice's `amount_due_cents` is set to 0 — recomputes the debtor's `total_outstanding_cents`, and may advance the parent case to `RECOVERED` per §3.6.

### 3.6. Payments, Waterfalls, Reversals, and Case Recovery

A debtor (an `Excavator` or `Locator`) pays by submitting a `Payment` with `payer_type` (`EXCAVATOR` or `LOCATOR`), `payer_id`, `amount_cents` greater than zero, and optionally `claim_invoice_id`. For the `Excavator` and `Locator` roles the caller's `X-User-ID` must equal `payer_id` (otherwise `ERR_OWNERSHIP_MISMATCH`); a `RecoveryManager` may record a payment on any debtor's behalf. The new payment starts in `APPLIED` and its `applied_at` is the current logical clock.

When `claim_invoice_id` is supplied, the payment applies as a single leg of the full `amount_cents` against that invoice; the amount must not exceed the invoice's `amount_due_cents` (otherwise `ERR_PAYMENT_EXCEEDS_BALANCE`, HTTP 409). When `claim_invoice_id` is omitted, the payment distributes via a waterfall across the payer's candidate invoices — those with `status` in `ISSUED` or `PARTIALLY_PAID` — ordered by `due_at` ascending with ties broken by `created_at` ascending. The walk fills each candidate to zero due before moving to the next: each leg is the smaller of the remaining unallocated amount and the candidate's `amount_due_cents`. Any remainder after all candidates are filled is added to the payer's `credit_balance_cents`. The computed legs are stored on the payment as an `allocations` array of `{ claim_invoice_id, amount_cents }` entries.

Each applied leg increases the target invoice's `amount_paid_cents`. An invoice whose `amount_paid_cents` becomes strictly greater than zero but strictly less than `invoiced_cents` moves to `PARTIALLY_PAID`; when `amount_paid_cents` reaches `invoiced_cents` the invoice moves to `PAID`. The first applied leg landing on any of a case's invoices moves the case's `recovery_status` from `INVOICED` to `COLLECTING`. When every invoice of a case reaches a terminal state (`PAID` or `WRITTEN_OFF`), the case's `recovery_status` moves to `RECOVERED`, with `total_recovered_cents` recomputed.

A `RecoveryManager` may reverse an `APPLIED` payment. Reversal moves the payment to `REVERSED`, undoes every allocation leg (each targeted invoice's `amount_paid_cents` is reduced and its status is recomputed from the resulting value: zero yields `ISSUED`, between zero and `invoiced_cents` yields `PARTIALLY_PAID`, equal to `invoiced_cents` yields `PAID`), reduces the payer's `credit_balance_cents` by any remainder leg this payment had created, and recomputes the case's `recovery_status` — in particular, if a terminal invoice reopens, the case moves from `RECOVERED` back to `COLLECTING`.

### 3.7. Repeat-Offender Scoring and Prevention Training

Each `Excavator` carries an `offender_points` total derived from its `ACTIVE` `ViolationRecord` rows. The base `points` of a violation are determined by the linked case's `severity`: 2 for `MINOR`, 4 for `MAJOR`, 6 for `CRITICAL`. The decay rule reads the violation's `created_at` against the current logical clock and produces an `effective_points` value per violation. The age in days is the floor of the elapsed seconds divided by 86400. A violation younger than 365 days contributes its full base points; a violation at least 365 days old but no more than 1095 days old contributes the floor of half its base points; a violation older than 1095 days contributes zero. The excavator's `offender_points` is the sum of these effective points across `ACTIVE` violations only — `OVERTURNED` rows are excluded. The score is recomputed whenever a violation is created, whenever a violation is overturned, whenever evaluate-program runs, and as part of the logical-clock sweep cadence. The band mapping is inclusive at every threshold: points at or above 18 yield `SUSPENDED`; at or above 12 yield `PROBATION`; at or above 6 yield `WATCH`; otherwise `GOOD_STANDING`.

A `RecoveryManager` may record a violation manually against an excavator for a case by supplying `excavator_id` and `damage_case_id`; the new `ViolationRecord` starts in `ACTIVE` with points derived from the case's `severity`, and the excavator's `offender_points` is recomputed — but the band is not re-applied until the next evaluate-program run. The same manager may overturn an `ACTIVE` violation; the row moves to `OVERTURNED` and `offender_points` is recomputed, again without re-banding.

The explicit evaluate-program capability recomputes the score and applies the band. Upgrades to a worse band apply freely. Downgrades to a better band are gated: leaving `PROBATION` or `SUSPENDED` requires every `TrainingAssignment` for this excavator whose course's `required_for_status` equals the current band to be `COMPLETED`. When the gate is unmet the band holds without error and the response shows the unchanged status.

When the band moves into `PROBATION` or `SUSPENDED` from a better band — whether from the explicit evaluate-program call or from the automatic cascade inside finalize — the training-assignment selector runs. The candidates are all `TrainingCourse` rows whose `required_for_status` equals the new band, iterated in `course_code` ascending order (a deterministic natural-key order). One `TrainingAssignment` is created per candidate, except that candidates for which the excavator already has an `ASSIGNED` assignment are skipped — no duplicates are created. When the candidate set is empty, no assignment is created and no error is raised. Each new assignment starts in `ASSIGNED` with `due_at` computed as ninety days after its `created_at` and `completed_at` null. An excavator completes an assignment by invoking complete; the caller's `X-User-ID` must equal the assignment's `excavator_id` (otherwise `ERR_OWNERSHIP_MISMATCH`), the assignment must currently be `ASSIGNED` (otherwise `ERR_INVALID_STATE`), and on success the status moves to `COMPLETED` with `completed_at` set. The manager may also assign a course directly by supplying `excavator_id` and `course_id`; the direct path also creates an `ASSIGNED` row with `due_at` ninety days out.

### 3.8. Disputes and Subrogation

A debtor disputes by opening a `Dispute` with `target_type` (`FAULT_ALLOCATION` or `CLAIM_INVOICE`), `target_id`, `reason` (one of `FAULT_SHARE`, `AMOUNT`, `EVIDENCE`, `OTHER`), and optional `detail` defaulting to an empty string. The `target_id` must resolve to an entity matching `target_type` — a mismatch is rejected with `ERR_DISPUTE_TARGET_MISMATCH` (HTTP 422). A target that already has a dispute in `OPEN`, `UNDER_REVIEW`, or `COUNTERED` rejects the new dispute with `ERR_DISPUTE_ALREADY_OPEN` (HTTP 409); this duplicate-dispute check is evaluated before the target-status check that follows, so when both would fire — for example, a second dispute against an invoice already in `DISPUTED` because of an existing `OPEN` dispute — the rejection is `ERR_DISPUTE_ALREADY_OPEN`. When the target is a `ClaimInvoice`, its `status` must be `ISSUED` or `PARTIALLY_PAID` (otherwise `ERR_INVALID_STATE`); when the target is a `FaultAllocation`, its `status` must be `PROPOSED` or `CONTESTED`. The new dispute starts in `OPEN`; `filed_by_type` is taken from the caller's role and `filed_by_id` from the caller's `X-User-ID`; `rounds` starts at 0; and `response_deadline_at` is computed as fourteen days after creation. When the target is a claim invoice, opening the dispute moves the invoice's `status` to `DISPUTED`.

The negotiation cycle runs between the filer and the adjuster. A `ClaimsAdjuster` responds to a dispute in `OPEN` or `COUNTERED`, optionally attaching a `response_note`, moving the dispute to `UNDER_REVIEW`, incrementing `rounds` by 1, and bumping `version`. The filer (an `Excavator` or `Locator` whose `X-User-ID` equals the dispute's `filed_by_id`) may counter a dispute in `UNDER_REVIEW`, optionally attaching a `counter_note`, moving it back to `COUNTERED` — a caller who is not the filer is rejected with `ERR_OWNERSHIP_MISMATCH`. The filer may accept the resolution from either `UNDER_REVIEW` or `COUNTERED`, moving the dispute to `RESOLVED`; the target invoice then leaves `DISPUTED` and its status is recomputed from `amount_paid_cents` per §3.6. Either a `ClaimsAdjuster` or a `RecoveryManager` may escalate a dispute in `OPEN`, `UNDER_REVIEW`, or `COUNTERED`, moving it to `ESCALATED`. Escalation creates a `SubrogationCase` in `DEMANDED` whose `dispute_id` is the escalated dispute, whose `claim_invoice_id` is set when the dispute's target was an invoice, whose `target_party_type` and `target_party_id` are the invoice's debtor, and whose `demand_amount_cents` is the invoice's `amount_due_cents` snapshot at escalation.

Settlement and closure of a subrogation case is the manager's domain. Recording a settlement supplies `recovered_cents` and `legal_cost_cents`, with the constraint that `legal_cost_cents` must not exceed `recovered_cents` (otherwise `ERR_INVALID_REQUEST`, HTTP 400). The waterfall splits the recovery deterministically: legal costs come off the top; then, when the case's `claim_invoice_id` is set, an amount up to the invoice's `amount_due_cents` is applied to the invoice (increasing `amount_paid_cents` and recomputing the invoice's status); any remainder after legal costs and the invoice application becomes `owner_share_cents`, the utility general fund's share. The three components — applied amount, `legal_cost_cents`, and `owner_share_cents` — sum exactly to `recovered_cents`. A successful settlement moves the case to `SETTLED` and bumps `version`. Either a `DEMANDED` or a `SETTLED` case may be closed, moving it to `CLOSED`.

### 3.9. Regulatory Filings and Case Closure

A `ClaimsAdjuster` creates a `RegulatoryReport` of `report_type` either `INCIDENT` or `QUARTERLY_SUMMARY`. An `INCIDENT` report requires `damage_case_id`; a `QUARTERLY_SUMMARY` report requires `damage_case_id` to be null and instead carries `period_start` and `period_end` describing a closed, inclusive interval. Two non-`SUPERSEDED` `QUARTERLY_SUMMARY` reports whose periods overlap — including sharing a boundary day — conflict, and the new report is rejected with `ERR_REPORT_PERIOD_OVERLAP` (HTTP 409). The create also accepts `payload_notes` defaulting to an empty string. The new report starts in `DRAFT` with `filed_at` null, `days_late` 0, `penalty_cents` 0, and `amends_report_id` null.

Filing a `DRAFT` report sets `status` to `FILED`, records `filed_at` from the logical clock, and computes lateness. The deadline is thirty days after the case's `occurred_at` for an `INCIDENT` report, or thirty days after the report's `period_end` for a `QUARTERLY_SUMMARY`; the boundary is inclusive, so filing exactly on the deadline is on time. Filing on or before the deadline yields `days_late` 0 and `penalty_cents` 0. Filing past the deadline yields `days_late` equal to the whole days between deadline and `filed_at` (at least 1), and a penalty equal to 5000 cents plus 500 cents per day late, capped at 100000 cents.

A `FILED` report may be amended. Amending creates a successor `RegulatoryReport` in `DRAFT` whose `amends_report_id` is the original report's id and whose `report_type`, `damage_case_id`, and period fields are copied from the original; the original moves to `SUPERSEDED`. Amending a report that is not `FILED` — still `DRAFT` or already `SUPERSEDED` — is rejected with `ERR_AMEND_CHAIN_BROKEN` (HTTP 409).

Case closure is the final act. A `RecoveryManager` closes a case when three conditions all hold: the case's `investigation_status` is `FAULT_FINAL`; its `recovery_status` is `RECOVERED`; and no `INCIDENT` `RegulatoryReport` for the case is still in `DRAFT`. When any condition fails, the close is rejected with `ERR_CASE_NOT_CLOSABLE` (HTTP 409). A successful close moves `investigation_status` to `CLOSED` and bumps the case's `version`.

## 4. Endpoint Definitions

All endpoints are mounted under `/damage-recovery`. Endpoints that create a new resource respond with HTTP 201; endpoints that modify an existing resource respond with HTTP 200; the cost-line delete responds with HTTP 204. The `POST /damage-recovery/_clock/set_current_utc` endpoint sets the logical clock and runs the expiry sweep; it responds with HTTP 200.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /damage-recovery/_clock/set_current_utc | Set the logical clock; runs the expiry sweep | RecoveryManager |
| POST | /damage-recovery/excavators | Register an excavating contractor | RecoveryManager |
| GET | /damage-recovery/excavators/{id} | Get an excavator | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| GET | /damage-recovery/excavators | List excavators | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| POST | /damage-recovery/excavators/{id}/evaluate-program | Recompute repeat-offender score and apply band | RecoveryManager |
| POST | /damage-recovery/locators | Register a locating contractor | RecoveryManager |
| GET | /damage-recovery/locators | List locators | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| POST | /damage-recovery/locators/{id}/suspend | Suspend a locator's contract | RecoveryManager |
| POST | /damage-recovery/locate-tickets | File a locate ticket | Excavator |
| GET | /damage-recovery/locate-tickets/{id} | Get a locate ticket | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| GET | /damage-recovery/locate-tickets | List locate tickets | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| POST | /damage-recovery/locate-tickets/{id}/renew | Extend an OPEN ticket's dig window | Excavator |
| POST | /damage-recovery/locate-responses | Submit a marking response against a ticket | Locator |
| GET | /damage-recovery/locate-responses/{id} | Get a locate response | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| GET | /damage-recovery/locate-responses | List locate responses | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| POST | /damage-recovery/locate-responses/{id}/audit | Audit a response's accuracy | DamageInvestigator |
| POST | /damage-recovery/damage-cases | Intake a damage report | IntakeCoordinator |
| GET | /damage-recovery/damage-cases/{id} | Get a damage case | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| GET | /damage-recovery/damage-cases | List damage cases | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| POST | /damage-recovery/damage-cases/{id}/link-ticket | Link a COMPLETED locate ticket to a case | IntakeCoordinator, DamageInvestigator |
| POST | /damage-recovery/damage-cases/{id}/begin-investigation | Claim an investigation | DamageInvestigator |
| POST | /damage-recovery/damage-cases/{id}/reconstruct-timeline | Rebuild the case's timeline | DamageInvestigator |
| POST | /damage-recovery/damage-cases/{id}/close | Close a fully resolved case | RecoveryManager |
| POST | /damage-recovery/evidence-items | Add a scene evidence item | IntakeCoordinator, DamageInvestigator |
| GET | /damage-recovery/evidence-items/{id} | Get an evidence item | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| GET | /damage-recovery/evidence-items | List evidence items | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| GET | /damage-recovery/timeline-events/{id} | Get a timeline event | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| GET | /damage-recovery/timeline-events | List timeline events | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| POST | /damage-recovery/fault-allocations | Create a fault allocation under OCC | DamageInvestigator |
| GET | /damage-recovery/fault-allocations/{id} | Get a fault allocation | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| GET | /damage-recovery/fault-allocations | List fault allocations | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| POST | /damage-recovery/fault-allocations/{id}/propose | Propose a DRAFT allocation | DamageInvestigator |
| POST | /damage-recovery/fault-allocations/{id}/contest | Contest a PROPOSED allocation | Excavator, Locator, RecoveryManager |
| POST | /damage-recovery/fault-allocations/{id}/revise | Revise a CONTESTED allocation back to DRAFT | DamageInvestigator |
| POST | /damage-recovery/fault-allocations/{id}/finalize | Finalize a PROPOSED allocation | RecoveryManager |
| POST | /damage-recovery/cost-line-items | Add a repair cost line | ClaimsAdjuster |
| GET | /damage-recovery/cost-line-items/{id} | Get a cost line | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| GET | /damage-recovery/cost-line-items | List cost lines | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| DELETE | /damage-recovery/cost-line-items/{id} | Remove a cost line while in COSTING | ClaimsAdjuster |
| GET | /damage-recovery/claim-invoices/{id} | Get a claim invoice | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| GET | /damage-recovery/claim-invoices | List claim invoices | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| POST | /damage-recovery/claim-invoices/{id}/issue | Issue a DRAFT invoice | ClaimsAdjuster |
| POST | /damage-recovery/claim-invoices/{id}/write-off | Write off a small uncollectable balance | RecoveryManager |
| POST | /damage-recovery/payments | Record a debtor payment | Excavator, Locator, RecoveryManager |
| GET | /damage-recovery/payments/{id} | Get a payment | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| GET | /damage-recovery/payments | List payments | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| POST | /damage-recovery/payments/{id}/reverse | Reverse an APPLIED payment | RecoveryManager |
| POST | /damage-recovery/disputes | Open a dispute | Excavator, Locator |
| GET | /damage-recovery/disputes/{id} | Get a dispute | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| GET | /damage-recovery/disputes | List disputes | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| POST | /damage-recovery/disputes/{id}/respond | Adjuster responds to a dispute | ClaimsAdjuster |
| POST | /damage-recovery/disputes/{id}/counter | Filer counters the response | Excavator, Locator |
| POST | /damage-recovery/disputes/{id}/accept-resolution | Filer accepts the resolution | Excavator, Locator |
| POST | /damage-recovery/disputes/{id}/escalate | Escalate to subrogation | ClaimsAdjuster, RecoveryManager |
| GET | /damage-recovery/subrogation-cases/{id} | Get a subrogation case | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| GET | /damage-recovery/subrogation-cases | List subrogation cases | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| POST | /damage-recovery/subrogation-cases/{id}/record-settlement | Record a settlement | RecoveryManager |
| POST | /damage-recovery/subrogation-cases/{id}/close | Close a subrogation case | RecoveryManager |
| POST | /damage-recovery/regulatory-reports | Create a regulatory report | ClaimsAdjuster |
| GET | /damage-recovery/regulatory-reports/{id} | Get a regulatory report | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| GET | /damage-recovery/regulatory-reports | List regulatory reports | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| POST | /damage-recovery/regulatory-reports/{id}/file | File a DRAFT report | ClaimsAdjuster |
| POST | /damage-recovery/regulatory-reports/{id}/amend | Amend a FILED report | ClaimsAdjuster |
| POST | /damage-recovery/violation-records | Manually record a violation | RecoveryManager |
| GET | /damage-recovery/violation-records/{id} | Get a violation record | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| GET | /damage-recovery/violation-records | List violation records | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| POST | /damage-recovery/violation-records/{id}/overturn | Overturn a violation | RecoveryManager |
| POST | /damage-recovery/training-courses | Create a prevention-training course | RecoveryManager |
| GET | /damage-recovery/training-courses/{id} | Get a training course | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| GET | /damage-recovery/training-courses | List training courses | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| POST | /damage-recovery/training-assignments | Assign a course to an excavator | RecoveryManager |
| GET | /damage-recovery/training-assignments/{id} | Get a training assignment | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| GET | /damage-recovery/training-assignments | List training assignments | IntakeCoordinator, DamageInvestigator, ClaimsAdjuster, RecoveryManager, Excavator, Locator |
| POST | /damage-recovery/training-assignments/{id}/complete | Complete an assigned course | Excavator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INVALID_REQUEST | 400 |
| ERR_FORBIDDEN_FOR_ROLE | 403 |
| ERR_OWNERSHIP_MISMATCH | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_CONTEST_WINDOW_CLOSED | 409 |
| ERR_TICKET_EXPIRED | 409 |
| ERR_DAMAGE_OUTSIDE_TICKET_WINDOW | 409 |
| ERR_REPORT_PERIOD_OVERLAP | 409 |
| ERR_LOCATOR_INACTIVE | 409 |
| ERR_AMEND_CHAIN_BROKEN | 409 |
| ERR_DISPUTE_ALREADY_OPEN | 409 |
| ERR_PROGRAM_SUSPENDED | 409 |
| ERR_NO_SCENE_EVIDENCE | 409 |
| ERR_INVOICE_AUTHORITY_CAP_EXCEEDED | 409 |
| ERR_WRITE_OFF_CAP_EXCEEDED | 409 |
| ERR_PAYMENT_EXCEEDS_BALANCE | 409 |
| ERR_TIMELINE_EMPTY | 409 |
| ERR_CASE_NOT_CLOSABLE | 409 |
| ERR_INVOICE_HAS_OPEN_DISPUTE | 409 |
| ERR_DUPLICATE_COURSE_CODE | 409 |
| ERR_TICKET_WINDOW_CONFLICT | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_EVIDENCE_INADMISSIBLE | 422 |
| ERR_TICKET_WINDOW_INVALID | 422 |
| ERR_DISPUTE_TARGET_MISMATCH | 422 |
| ERR_SHARES_MUST_SUM_10000 | 422 |

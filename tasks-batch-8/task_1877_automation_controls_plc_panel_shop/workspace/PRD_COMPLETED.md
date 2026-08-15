# UL 508A Panel Shop API — Product Requirements Document

## 1. Introduction

A UL 508A–certified industrial control panel shop coordinates a deeply nested workflow: a customer signs a contract for one or more control panels, each panel passes through design review, procurement of UL-listed components, point-to-point wiring verification, UL label affixing, shipment, and on-site startup commissioning. Throughout this lifecycle the shop must enforce segregation of duties (the engineer who designs a panel may not verify its wiring or approve its substitutions), maintain a weakest-link short-circuit current rating per panel, price change orders against a running contract ledger, and honor a control-logic warranty that decays as the commissioned equipment ages.

The system described here exposes that workflow as a REST API mounted under `/panel-shop`. Nine roles interact with the shop — `ProjectManager`, `QAManager`, `DesignEngineer`, `ShopLead`, `TestTechnician`, `ControlsEngineer`, `FieldEngineer`, `ShippingClerk`, and `Customer` — each owning a distinct slice of the operation. The shop's discipline comes from three mechanical pillars: a state machine per aggregate (Job, Panel, SubstitutionRequest, TestPoint, TestSession, ProgramVersion, StartupSession, ChangeOrder, WarrantyClaim, AsBuiltPackage), a set of derived calculations (SCCR weakest-link, BOM cost rollup, change-order pricing, warranty liability with provisional and final variants, startup labor billing, as-built completeness, and a compound job-posture engine), and optimistic concurrency control on the small set of writes where a stale read could otherwise overwrite another writer's ledger or release. A dedicated logical-clock endpoint supports deterministic time-based testing; the shop's time never silently falls back to wall clock.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two HTTP headers: `X-User-ID` and `X-User-Role`. A request missing either header (an empty header value counts as missing), or carrying a role string that is not one of the nine declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not listed in the target endpoint's Authorized Role(s) column is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The nine role names are spelled exactly: `ProjectManager`, `QAManager`, `DesignEngineer`, `ShopLead`, `TestTechnician`, `ControlsEngineer`, `FieldEngineer`, `ShippingClerk`, and `Customer`.

Identity semantics differ across roles. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` record; ownership checks on any `Job`, `ChangeOrder`, or `SubstitutionRequest` compare the resource's `customer_id` foreign key (or the customer of the owning chain) to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). For the other eight roles (`ProjectManager`, `QAManager`, `DesignEngineer`, `ShopLead`, `TestTechnician`, `ControlsEngineer`, `FieldEngineer`, `ShippingClerk`), `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `design_engineer_id` on a `Panel`, `technician_id` on a `TestSession`, `engineer_id` on a `StartupSession`, or `requested_by_id` on a `SubstitutionRequest` or `ChangeOrder`) but does not compare it to any entity's `id` except where a segregation-of-duties rule or an explicit same-user precondition (such as a withdraw-by-requester rule) says otherwise.

### 2.2. API Response Structure

Every response, whether success or error, conforms to one canonical envelope.

**Success envelope:**

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "object",
  "data": { }
}
```

For a single resource fetch or mutation, `response_type` is `"object"` and `data` is the resource representation. For a list endpoint, `response_type` is `"array"`, `data` is the array of resources, and `meta` additionally carries the pagination fields (`limit`, `offset`, `total_count`, `has_more`).

**Error envelope:**

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "Human-readable description of the failure."
  }
}
```

`api_request_id` is a server-generated request identifier with the prefix `req_`. `api_request_timestamp` is the server's receipt time in ISO 8601 UTC with millisecond precision. Error responses use the same `meta` block; `data.error_id` is the machine-stable identifier catalogued in §5, and `data.message` is a human-readable elaboration that is free to vary. A request that matches no declared route — or a path with an unsupported method — is likewise answered in the canonical envelope with `ERR_NOT_FOUND` (HTTP 404).

### 2.3. Pagination

All list endpoints accept optional `limit` and `offset` query parameters. `limit` defaults to `10`, has a minimum of `1` and a maximum of `100`; `offset` defaults to `0`. Results are sorted by `created_at` ascending, with ties (common under the logical clock) broken by creation — that is, insertion — order. The `meta` block of a list response includes `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the total number of matching records before pagination and `has_more` is true exactly when `offset + limit < total_count`.

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id` — a UUID with no type prefix — assigned at creation. Every resource carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits recorded at creation.

Most entities additionally carry `updated_at` (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and `version` (an integer starting at `1` on creation and incremented by exactly `1` on every state transition, side-effect write, or PATCH of that entity). A pure recomputation of a derived field — such as a panel's `sccr_rating_ka` or an as-built package's `completeness_pct` — does not by itself increment the host entity's `version`; only an accompanying state transition or an explicit PATCH does. The two exceptions are `TestPoint` and `ProgramVersion`, which carry `id` and `created_at` only — both `updated_at` and `version` are absent on those two resources. Their mutations are tracked through the parent `TestSession` or `Panel` aggregate's own `version`.

### 2.5. Logical Clock and Time-Dependent Rules

The server maintains a logical clock initialized to exactly `2026-08-01T00:00:00Z`. The logical clock does not silently fall back to wall-clock time; it advances only when a caller with role `ProjectManager` or `QAManager` invokes the test-driving capability that sets the logical clock to a supplied `to_iso8601` instant. The supplied instant is applied verbatim — the clock may be set to any parseable ISO 8601 time, including one earlier than the current value — and the endpoint responds with an object carrying the new clock as `current_utc`. Advancing the logical clock past a `StartupSession`'s `scheduled_end` while that session is still in `SCHEDULED` fires the no-show sweep, transitioning the session to `NO_SHOW`. The same sweep is evaluated on any read or write of the affected session, so a no-show never lingers invisible.

### 2.6. Optimistic Concurrency Control

Three write endpoints are guarded by optimistic concurrency control. Each names an `expected_*_version` field that the request body must carry as a non-optional integer; the server compares that value against the parent entity's current `version`, and on a mismatch rejects the request with `ERR_STALE_VERSION` (HTTP 412).

- Creating a `ProgramVersion` against a `Panel` requires `expected_panel_version` to match the panel's current `version`. Because a successful release supersedes the prior `RELEASED` version and increments the panel's `version`, a writer whose last read of the panel predates another release would otherwise overwrite state they have not observed; the OCC check surfaces that as `ERR_STALE_VERSION`.
- Approving a `ChangeOrder` requires `expected_job_version` to match the job's current `version`. Because approval posts to the job's `approved_co_delta_cents` ledger and recomputes `contract_price_cents`, approving against a stale baseline would compound errors across the ledger; the OCC check rejects the approval with `ERR_STALE_VERSION`.
- Rescinding an `APPROVED` `ChangeOrder` requires `expected_job_version` to match the job's current `version`. Rescind is a compensating action that subtracts the order's `computed_delta_cents` from the ledger; it must subtract from the exact baseline the client read, so a stale-version rescind is rejected with `ERR_STALE_VERSION`.

Endpoints not listed above do not accept a version field.

### 2.7. Precision, Rounding, and Integer Currency

All monetary amounts are integer cents. Where a calculation's result must be integral, the rounding method is round-half-up at the explicitly stated step. Panel SCCR ratings are integer kiloamperes with no rounding. `AsBuiltPackage.completeness_pct` is an integer percent in `[0, 100]` rounded half-up. `labor_hours` on a `StartupSession` and `claimed_labor_hours` on a `WarrantyClaim` are decimal numbers of hours; every multiplication involving them rounds half-up at the step the calculation names. `discount_pct` on a `ChangeOrder` is a decimal in the closed range `[0, 0.5]`. Where a calculation specifies "rate first, then multiply" (startup labor) or "line first, then sum" (BOM rollup), that rounding order is part of the contract and is not interchangeable with the more obvious alternative.

### 2.8. Segregation of Duties

UL 508A panel shops require that the person who authors a design is not the person who verifies it. The API enforces this at five points, all rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403):

- `QAManager` approving a panel's design must have a user id different from that panel's `design_engineer_id`.
- `QAManager` affixing the UL 508A label must have a user id different from that panel's `design_engineer_id`.
- `QAManager` approving an as-built package must have a user id different from the owning panel's `design_engineer_id`.
- `TestTechnician` opening a test session on a panel must have a user id different from that panel's `design_engineer_id`.
- `QAManager` approving a substitution request must have a user id different from the request's `requested_by_id`.

A separate same-user rule in the other direction governs withdrawal: only the `DesignEngineer` whose id matches a `SubstitutionRequest`'s `requested_by_id` may withdraw that request, and only the `ProjectManager` whose id matches a `ChangeOrder`'s `requested_by_id` may withdraw that change order. These same-user checks run after the target entity's state precondition and a violation surfaces as `ERR_UNAUTHORIZED` (HTTP 403).

### 2.9. Validation Priority Ordering

When a request fails more than one validation, the server reports the failure with the lowest priority number. The declared order, from highest precedence to lowest:

1. `ERR_UNAUTHENTICATED` — headers missing or role string unknown.
2. `ERR_UNAUTHORIZED` — role not in the endpoint's authorized set.
3. `ERR_NOT_RESOURCE_OWNER` — `Customer` identity mismatch on the owning chain.
4. `ERR_NOT_FOUND` — path-templated resource missing, validated left-to-right (customer, then job, then panel, then child).
5. `ERR_REFERENCE_NOT_FOUND` — body-referenced foreign key missing (`customer_id`, `component_id`, `panel_id`, `original_line_id`, `proposed_component_id`).
6. `ERR_INVALID_STATE` — target entity not in a state from which the requested transition is defined.
7. `ERR_STALE_VERSION` — OCC `expected_*_version` mismatch.
8. `ERR_SEGREGATION_OF_DUTIES` — SoD violations listed in §2.8.
9. `ERR_SCCR_BELOW_MINIMUM` — submit-review with `sccr_rating_ka` below the 5 kA floor.
10. `ERR_SUBSTITUTION_DOWNRATED` — substitution approval that would lower the SCCR chain or references an inactive proposed component.
11. `ERR_OUTSIDE_SCHEDULED_WINDOW` — startup begin outside the `[scheduled_start, scheduled_end]` window.
12. `ERR_WARRANTY_EXPIRED` — claim filed or triaged past `warranty_expires_at`, or the job is not yet commissioned.
13. `ERR_ENGINEER_DOUBLE_BOOKED` — half-open window overlap for the same `engineer_id`.
14. `ERR_PANEL_TURNOVER_VIOLATION` — same-panel turnover buffer violated.
15. `ERR_COMPONENT_INACTIVE` — referencing an inactive component in a new BOM line or substitution request.
16. `ERR_DUPLICATE` — uniqueness violation on `part_number`, `content_hash` per panel, `version_tag` per panel, `panel_tag` per job, `job_number` per customer, or duplicate component on a panel.
17. `ERR_CREDIT_HOLD` — customer credit hold blocking job creation, job advance, substitution approval, or change-order approval.
18. `ERR_INVALID_REQUEST` (fiscal) — `discount_pct` outside `[0, 0.5]`, missing `price_delta_cents`, `quoted_price_cents` negative, or `warranty_months` outside `[0, 60]`.
19. `ERR_CLAIM_INADMISSIBLE` — claim against a job with no commissioned panel, or negative labor hours.
20. `ERR_REMOTE_ACCESS_REQUIRED` — `REMOTE` support mode without `remote_access_granted`.
21. `ERR_TEST_POINTS_UNDECIDED` — completing a session with `UNTESTED` points, or recording a result on a non-`UNTESTED` point or non-`OPEN` session.
22. `ERR_INVALID_REQUEST` (shape) — missing required fields, wrong types, enum violations; and `ERR_INVALID_REQUEST_BODY` for malformed JSON.

So, for example, a `ChangeOrder` approval that fails both RBAC and OCC reports `ERR_UNAUTHORIZED`, not `ERR_STALE_VERSION`; a panel submit-review on a panel with no BOM lines and an SCCR of 3 reports the SCCR floor error because the no-BOM-line condition surfaces through state/routing checks earlier in the ordering.

The three gate errors not numbered above slot into the order as follows: `ERR_PANEL_NOT_READY` and `ERR_JOB_GATE_BLOCKED` are evaluated immediately after the target entity's state check (priority 6), except where a numbered rule explicitly precedes them — as `ERR_SCCR_BELOW_MINIMUM` (priority 9) does on submit-review; `ERR_BACKUP_REQUIRED` is evaluated last on startup completion, after all field-shape checks.

### 2.10. Nested Resource Existence, Left to Right

URLs in this API are hierarchically templated (customer → job → panel → child resource). When a path names multiple identifiers, the server validates them left to right: a nonexistent customer id surfaces `ERR_NOT_FOUND` before the panel id is even consulted. A path whose identifiers exist but do not nest correctly (for example, a `panel_id` that belongs to a different `job_id` than the one in the URL) is also reported as `ERR_NOT_FOUND`, preserving the rule that a client cannot probe for the existence of resources outside its scope.

## 3. Business Logic & Workflows

### 3.1. Customer Intake, Job Creation, and the Compound Job Posture

A `ProjectManager` registers a new customer by supplying the legal `company_name`, the `site_state_code` (a free-form non-empty string, conventionally a two-letter state code, which drives freight zone and the dispatch tier for warranty labor — no length or format check is enforced), and optionally `credit_hold` (defaulting to `false`) and `warranty_labor_tier` (one of `TIER_LOCAL`, `TIER_REGIONAL`, `TIER_NATIONAL`, defaulting to `TIER_REGIONAL`). A later customer update by the `ProjectManager` lets them modify `credit_hold` or `warranty_labor_tier`; each successful update increments the customer's `version` by one.

With a customer on file, the `ProjectManager` opens a job by supplying `customer_id`, a human-readable `job_number` that must be unique within that customer, a `quoted_price_cents` contract baseline that must be at least zero, and optionally `warranty_months` for the control-logic warranty, which must lie in the closed range `[0, 60]` and defaults to `12`. Two fiscal validators run on job creation: a negative `quoted_price_cents` or an out-of-range `warranty_months` is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and creating a job for a customer whose `credit_hold` is `true` is rejected with `ERR_CREDIT_HOLD` (HTTP 402).

A job begins life in `OPEN`. Its `status` is a compound posture over the open set `{OPEN, DESIGN, PROCUREMENT, BUILD, TEST, READY_TO_SHIP, SHIPPED, COMMISSIONED, CLOSED, ON_HOLD}`, derived from its child panels and re-evaluated on every mutation of a panel, panel BOM line, as-built package, or startup session. The derivation is deterministic and evaluated top-down: with no panels the job is `OPEN`; else if any panel is in `DESIGN` or `DESIGN_REVIEW` the job is `DESIGN`; else if any BOM line across the job's panels is in `PENDING` or `ORDERED` the job is `PROCUREMENT`; else if any panel is in `PROCUREMENT` or `WIRING` the job is `BUILD`; else if any panel is in `POINT_TO_POINT` or `TEST_FAILED` the job is `TEST`; else if every panel is in `{TEST_PASSED, READY_FOR_LABEL, LABELED, SHIPPED, COMMISSIONED}` and every panel's as-built package is `RELEASED` and not every panel is `SHIPPED` or `COMMISSIONED`, the job is `READY_TO_SHIP`; else if every panel is `SHIPPED` (or a mix of `SHIPPED` and `COMMISSIONED`) the job is `SHIPPED`; else when every panel is `COMMISSIONED` the job is `COMMISSIONED`. If none of the above matches — panels past point-to-point whose as-built gate has not yet cleared and which are not all shipped — the derivation yields `TEST`. A single re-evaluation loops until no declared auto-transition applies, so one mutation may fire several auto-advances in sequence (each incrementing the job's `version` by one). The engine never fires while the job is `ON_HOLD` or `CLOSED`. Posture changes only ever fire through declared transitions; the engine never silently rewrites `status` outside one.

The `ProjectManager` may move a job from `OPEN` to `DESIGN` by an explicit advance action; the same transition also fires automatically when the first `Panel` for the job is created. Either way the job's `version` increments by one. The advance is gated on the customer's credit: if `credit_hold` is `true`, the advance is rejected with `ERR_CREDIT_HOLD`. Once the job has at least one panel and every panel has left `DESIGN` and `DESIGN_REVIEW`, the job auto-advances `DESIGN → PROCUREMENT`. When every BOM line across every panel has reached `RECEIVED` or `SUBSTITUTED`, the job auto-advances `PROCUREMENT → BUILD`. When every panel has reached `POINT_TO_POINT` or beyond (any of `POINT_TO_POINT`, `TEST_PASSED`, `TEST_FAILED`, `READY_FOR_LABEL`, `LABELED`, `SHIPPED`, `COMMISSIONED`), the job auto-advances `BUILD → TEST`. When every panel is in `{TEST_PASSED, READY_FOR_LABEL, LABELED, SHIPPED, COMMISSIONED}` and every panel's as-built package is `RELEASED`, the job auto-advances `TEST → READY_TO_SHIP`. Each auto-advance increments the job's `version` by one.

A mid-flight job can be paused: the `ProjectManager` may place a job in `ON_HOLD` from any of `DESIGN`, `PROCUREMENT`, `BUILD`, or `TEST`. Resuming from `ON_HOLD` requires the customer's `credit_hold` to be `false`; the posture engine immediately re-derives `status` from the children, with `DESIGN` as the floor. Both hold and resume increment the job's `version` by one.

When the job is `READY_TO_SHIP`, a `ShippingClerk` triggers shipment. The transition cascades: every panel in `TEST_PASSED`, `READY_FOR_LABEL`, or `LABELED` transitions to `SHIPPED` with `shipped_at` set to the current time, and the job's `version` increments by one. A ship call against a job that is not in `READY_TO_SHIP` is rejected with `ERR_JOB_GATE_BLOCKED` (HTTP 409). When every panel of a shipped job reaches `COMMISSIONED`, the job auto-transitions `SHIPPED → COMMISSIONED` and the server writes `warranty_expires_at` equal to the latest `commissioned_at` across the job's panels plus `warranty_months` calendar months (calendar-month addition clamps the day-of-month to the target month's last day — e.g. January 31 plus one month lands on the last day of February). Before that moment, `warranty_expires_at` is null.

The `ProjectManager` closes a commissioned job only when no `ChangeOrder` of the job remains in `PROPOSED` or `REVISED` and no `WarrantyClaim` of the job remains in `FILED`, `TRIAGED`, or `ACCEPTED`; a close that violates either gate is rejected with `ERR_JOB_GATE_BLOCKED`. A successful close moves the job `COMMISSIONED → CLOSED` and increments its `version`.

### 3.2. Panel Design, Bill of Materials, and the SCCR Weakest-Link Chain

A `DesignEngineer` creates a panel under a job by supplying a `panel_tag` (the physical nameplate designation, such as `MCC-01`, unique within the job), a NEMA `enclosure_rating` drawn from `{NEMA_1, NEMA_12, NEMA_4, NEMA_4X}`, and the `design_engineer_id` of the authoring engineer — a value the system records for later segregation-of-duties checks. Panel creation has two cascading side effects: if the parent job was in `OPEN`, it advances to `DESIGN`; and an `AsBuiltPackage` is auto-created for the panel with all four document flags set to `false`. Panel creation is not otherwise gated on the parent job's status; when the job is not `OPEN` the posture engine simply re-derives. A duplicate `panel_tag` within the same job is rejected with `ERR_DUPLICATE` (HTTP 409).

The new panel starts in `DESIGN`. Its BOM is built line by line: the `DesignEngineer` adds a `PanelComponent` by referencing a catalog `component_id` and a `quantity` of at least one. Adding a line does several things at once: it captures the catalog's current `unit_cost_cents` into the line's `unit_cost_snapshot_cents` (so a later catalog price change cannot drift an as-built BOM), it computes the line's `extended_cost_cents` as `quantity` multiplied by `unit_cost_snapshot_cents` rounded half-up to integer cents, and it triggers a recompute of the panel's `sccr_rating_ka` and the BOM cost rollup. Adding a line whose `component_id` references an inactive component is rejected with `ERR_COMPONENT_INACTIVE` (HTTP 422); adding the same component twice to the same panel is rejected with `ERR_DUPLICATE`. A BOM-line update by the `DesignEngineer` changes `quantity` while the line is still `PENDING`; that re-computes `extended_cost_cents` and increments the line's `version`. A `ShopLead` marks an `ORDERED` line as `RECEIVED` via the receive action, which increments the line's `version` and re-evaluates the job posture.

The panel's `sccr_rating_ka` is computed by a weakest-link algorithm over the panel's power-circuit lines. The input set is every BOM line whose `line_status` is one of `PENDING`, `ORDERED`, `RECEIVED`, or `SUBSTITUTED` and whose referenced component's `component_class` is one of `DISCONNECT`, `BRANCH_PROTECTIVE`, `CONTACTOR`, `OVERLOAD`, or `POWER_SUPPLY`, with a non-null `sccr_ka`; lines whose component is in `CONTROL_POWER`, `WIRE_DUCT`, `TERMINAL`, `PLC_IO`, or `PILOT_DEVICE`, or whose component carries a null `sccr_ka`, are excluded from the min-chain. If the resulting power-line set is empty, `sccr_rating_ka` is `0`. Otherwise the baseline is the minimum `sccr_ka` across the set — except that if any line's component is a current-limiting branch-protective device (a `BRANCH_PROTECTIVE` with `sccr_ka` of at least `100`), every `CONTACTOR` or `OVERLOAD` in the set has its `sccr_ka` raised to a floor of `25` before the minimum is taken; the panel's rating is then that raised minimum. The constants `25` and `100` are fixed by UL 508A practice. The rating is recomputed on BOM line creation, on substitution approval, and on panel submit-review.

Once a panel has at least one BOM line and its `sccr_rating_ka` is at least `5` (the UL 508A minimum labelable SCCR), the `DesignEngineer` may submit the panel for design review, transitioning `DESIGN → DESIGN_REVIEW`. A submit-review against a panel whose SCCR is below the floor is rejected with `ERR_SCCR_BELOW_MINIMUM` (HTTP 422); a submit-review against a panel with no BOM lines is rejected with `ERR_PANEL_NOT_READY` (HTTP 409).

In `DESIGN_REVIEW`, a `QAManager` other than the panel's `design_engineer_id` may approve the design (`DESIGN_REVIEW → DESIGN_APPROVED`); a self-approval is rejected with `ERR_SEGREGATION_OF_DUTIES`. The same `QAManager` may instead reject the design, returning the panel to `DESIGN` for revision — this revision loop is the panel's primary cycle, and each leg of it increments the panel's `version` by one.

When the design is approved, the `ProjectManager` releases procurement, transitioning `DESIGN_APPROVED → PROCUREMENT`. The release is gated on the parent job being in `DESIGN` or `PROCUREMENT`; a release against a job that has progressed further is rejected with `ERR_JOB_GATE_BLOCKED`. Releasing cascades every `PENDING` BOM line of the panel to `ORDERED` and increments the panel's `version`.

After every BOM line of the panel has reached `RECEIVED` or `SUBSTITUTED`, the `ShopLead` begins wiring, transitioning `PROCUREMENT → WIRING`. When at least one `TestPoint` exists for the panel, the `ShopLead` begins point-to-point testing, transitioning `WIRING → POINT_TO_POINT`; beginning test on a panel with no test points is rejected with `ERR_PANEL_NOT_READY`. The test outcome and label flow are described in §3.4 and §3.6.

### 3.3. Catalog, Substitution Requests, and the Lead-Time Delta

The shop's component catalog is owned by the `QAManager`, who registers each `Component` with a globally unique `part_number` (a duplicate is rejected with `ERR_DUPLICATE`), a `component_class` drawn from `{DISCONNECT, BRANCH_PROTECTIVE, CONTACTOR, OVERLOAD, CONTROL_POWER, PLC_IO, TERMINAL, WIRE_DUCT, PILOT_DEVICE, POWER_SUPPLY}`, the current `unit_cost_cents` and `lead_time_days` (both non-negative integers), the component-level `sccr_ka` in kiloamperes (nullable for any class — conventionally only `WIRE_DUCT` and `TERMINAL` carry no fault rating; when present it must be an integer of at least `1`), the worst-case `heat_dissipation_w` at full load (a non-negative number), and an `active` flag defaulting to `true`. The `QAManager` may later update a component's `lead_time_days`, `unit_cost_cents`, or `active` flag; updated `lead_time_days` and `unit_cost_cents` values must remain non-negative integers, and each such update increments the component's `version`. The catalog list's `active` query filter accepts only the strings `true` and `false` (case-insensitive); any other value is rejected with `ERR_INVALID_REQUEST`. Inactive components may not be referenced by a new BOM line or a new substitution request — both are rejected with `ERR_COMPONENT_INACTIVE` — but they remain readable for existing as-built records.

When a BOM line's component is unavailable (long lead time, obsolescence, cost), the `DesignEngineer` files a `SubstitutionRequest` against the panel, supplying the `original_line_id`, the `proposed_component_id`, and a free-text `reason`. The referenced original line need only be an existing BOM line of the panel; its `line_status` is not gated at filing time. The new request begins in `REQUESTED` with `requested_by_id` recorded from the acting `DesignEngineer`.

The negotiation is cyclic between the engineer and the customer. The owning `Customer` (whose id must equal the job's `customer_id`, else `ERR_NOT_RESOURCE_OWNER`) may counter a `REQUESTED` request, transitioning it to `COUNTERED`. The `DesignEngineer` may then resubmit a `COUNTERED` request, returning it to `REQUESTED`. Either party may end the loop: the `QAManager` may reject a `REQUESTED` request (terminal `REJECTED`); the `DesignEngineer` whose id matches `requested_by_id` may withdraw a `REQUESTED` request (terminal `WITHDRAWN`). Each leg of the loop increments the request's `version` by one.

Approval is the heart of the workflow. A `QAManager` whose id differs from the request's `requested_by_id` may approve from either `REQUESTED` or `COUNTERED`; a self-approval is rejected with `ERR_SEGREGATION_OF_DUTIES`. Approval is gated on three further checks, applied in §2.9 priority order: when both the proposed and original components carry a non-null `sccr_ka`, the proposed component's `sccr_ka` must be at least the original's (else `ERR_SUBSTITUTION_DOWNRATED`, HTTP 422); the proposed component must be active (else `ERR_COMPONENT_INACTIVE`); and the owning job's customer must not be on `credit_hold` (else `ERR_CREDIT_HOLD`).

Approval has a wide cascade of side effects. A new `PanelComponent` line is created on the same panel, referencing the `proposed_component_id`, with `quantity` copied from the original line, `line_status` set to `SUBSTITUTED`, `substituted_for_id` pointing back to the original line, and `unit_cost_snapshot_cents` captured from the proposed component's current `unit_cost_cents`. The original line is retired from the active BOM: if its `line_status` was `PENDING` or `ORDERED`, it is set to `SUBSTITUTED` as a superseded marker; if it was already `RECEIVED`, it stays `RECEIVED` for receipt-audit purposes but is excluded from both the BOM cost rollup and the SCCR weakest-link input sets (those input sets include a line only when no other line references it via `substituted_for_id`). The panel's `sccr_rating_ka` is recomputed under the new component mix, and the request's `sccr_impact_ka` records what the panel's rating would be after approval — a value captured for audit even if the rating is later recomputed. The request's `lead_time_delta_days` is computed by the variant of the lead-time calculation selected by the parent job's current status, and the request's `version` increments by one.

The lead-time delta itself is signed: `Component(proposed).lead_time_days` minus `Component(original).lead_time_days`. Two variants apply. When the parent job is in `DESIGN` or `PROCUREMENT` — early-phase jobs where the shop absorbs raw vendor deltas plus a risk pad — the reported delta is the raw delta plus `7` days when the raw delta is positive, or the raw delta unchanged when it is zero or negative; the pad never applies to a decrease. When the parent job is in `BUILD`, `TEST`, `READY_TO_SHIP`, `SHIPPED`, or `COMMISSIONED` — late-phase jobs where expediting is assumed to erase increases — the reported delta is the minimum of the raw delta and zero; increases are reported as zero because the shop expedites, while decreases are kept as-is.

### 3.4. Point-to-Point Testing: Test Plan, Sessions, and the Rework Loop

Before testing can begin, the `DesignEngineer` builds the panel's test plan as a list of `TestPoint`s, each with a `point_label` (a wire-number / terminal designation such as `TB1-14 to PLC-I0.3`), an `expected_signal` drawn from `{CONTINUITY, VOLTAGE_24VDC, VOLTAGE_120VAC, ANALOG_4_20MA, ISOLATION}`, and a `sequence_no` unique within the panel and at least `1`. Every test point begins with `result` set to `UNTESTED`. Test points may be added while the panel is in any status.

A `TestTechnician` opens a `TestSession` on a panel in `POINT_TO_POINT` by supplying their own `technician_id`; if that id equals the panel's `design_engineer_id` the open is rejected with `ERR_SEGREGATION_OF_DUTIES`. The session starts in `OPEN` with `started_at` set, `completed_at` null, and both `pass_count` and `fail_count` at zero.

While the session is `OPEN`, the technician records results point by point, supplying a `test_point_id` and an `outcome` of `PASS`, `FAIL`, or `SKIPPED`. Recording a result requires the parent session to be `OPEN` and the point to currently be `UNTESTED`; violations of either are rejected with `ERR_TEST_POINTS_UNDECIDED` (HTTP 422). A `PASS` outcome increments the session's `pass_count` by one; a `FAIL` increments `fail_count` by one; a `SKIPPED` increments neither. Each record-result call increments the session's `version` by one, and the response body is the updated `TestPoint` resource.

Completion requires every test point of the panel to be decided — no `UNTESTED` points may remain, though `SKIPPED` is allowed — and the acting `TestTechnician`'s id must equal the session's `technician_id` (only the executing technician completes the session). A complete call with any `UNTESTED` point outstanding is rejected with `ERR_TEST_POINTS_UNDECIDED`; a complete or abort call against a non-`OPEN` session is rejected with `ERR_INVALID_STATE`; and a complete call from a technician whose id differs from the session's `technician_id` is rejected with `ERR_UNAUTHORIZED` (HTTP 403). On a successful complete, the session transitions `OPEN → COMPLETED`, `completed_at` is set, the session's `version` increments, and the panel auto-transitions: if the completed session has `fail_count` of zero and no point is `SKIPPED` — meaning every point has `result` equal to `PASS` — the panel moves `POINT_TO_POINT → TEST_PASSED` and the as-built package's `has_test_report` flag is set to `true` with a completeness recompute; if the completed session has `fail_count` of at least one, the panel moves `POINT_TO_POINT → TEST_FAILED` instead. A completed session with `fail_count` of zero but at least one `SKIPPED` point fires no panel transition — the panel remains in `POINT_TO_POINT`.

A failed panel re-enters the shop floor: the `ShopLead` triggers a rework, transitioning `TEST_FAILED → WIRING`. The rework cascades every test point of the panel whose `result` was `PASS`, `FAIL`, or `SKIPPED` back to `UNTESTED`, and increments the panel's `version`.

An `OPEN` session may instead be aborted by the `TestTechnician`. Abort resets every test point recorded by this session — those with `result` in `{PASS, FAIL, SKIPPED}` — back to `UNTESTED`, recomputes the session's `pass_count` and `fail_count` to zero, transitions the session `OPEN → ABORTED`, and increments the session's `version`. The panel's own status is unchanged by an abort.

### 3.5. PLC Program Version Control and Site Backup Evidence

A `ControlsEngineer` manages the panel's PLC program as a chain of `ProgramVersion`s. Each version carries a human `version_tag` (such as `v1.2.0`, unique within the panel; duplicates are rejected with `ERR_DUPLICATE`) and a `content_hash` — conventionally the SHA-256 hex of the compiled program archive, also unique within the panel, though no hash-format check is enforced and any non-empty string is accepted; a duplicate hash is likewise rejected with `ERR_DUPLICATE`. Program-version creation is not gated on the panel's status. A version carries a `site_backup_taken` flag defaulting to `false`.

Release happens through a single create-with-release path; there is no separate release action. The `ControlsEngineer` posts a new `ProgramVersion` directly against the panel, supplying `version_tag`, `content_hash`, optionally `site_backup_taken`, and the OCC field `expected_panel_version`. The create succeeds only when `expected_panel_version` equals the panel's current `version`; on a mismatch the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The new version is created directly in `RELEASED` with `released_at` set to the current time — because the only creation path is create-with-release, the `DRAFT` state is not reachable through the API. The create supersedes every other version of the same panel that was previously `RELEASED` (each such version transitions to `SUPERSEDED`) and increments the panel's `version` by one — the panel's `version` is the OCC anchor that future create-with-release calls are validated against. Because `ProgramVersion` itself carries no `version` field, the panel aggregate owns the concurrency anchor for the whole release operation.

A `SUPERSEDED` version may be archived by the `ControlsEngineer`, transitioning to terminal `ARCHIVED`; the archive action also accepts a `DRAFT` version (defensively, since `DRAFT` is unreachable through the API). Once archived, a version is no longer mutable.

A `FieldEngineer` marks the site backup evidence on a `RELEASED` version via the mark-site-backup action, setting `site_backup_taken` to `true`. This flag is the commissioning evidence the startup workflow checks: completing a startup session requires that the panel have a `RELEASED` program version whose `site_backup_taken` is `true`, and the panel's own transition from `SHIPPED` to `COMMISSIONED` requires the same condition. A complete attempt without such a version is rejected with `ERR_BACKUP_REQUIRED` (HTTP 422).

### 3.6. UL 508A Labeling and the As-Built Documentation Package

After a panel passes point-to-point testing, the `QAManager` requests the UL 508A label, transitioning `TEST_PASSED → READY_FOR_LABEL`. The request is gated on two checks: at least one `ProgramVersion` of the panel must be in `RELEASED` (else `ERR_PANEL_NOT_READY`), and no `SubstitutionRequest` of the panel may remain in `REQUESTED` or `COUNTERED` (else `ERR_PANEL_NOT_READY`).

With the panel in `READY_FOR_LABEL`, a `QAManager` whose id differs from the panel's `design_engineer_id` affixes the label, transitioning to `LABELED`. Affixing mints the panel's `label_serial` in the exact format `UL-<job_number>-<panel_tag>-1`, where `<job_number>` and `<panel_tag>` are interpolated from the parent job and the panel itself and the trailing `1` is the sequence. Affixing also sets the as-built package's `has_ul_label_photo` flag to `true`, triggers a completeness recompute, and increments the panel's `version`. A self-affix by the panel's designer is rejected with `ERR_SEGREGATION_OF_DUTIES`.

The `AsBuiltPackage` is the panel's documentation record, auto-created at panel creation with all four flags — `has_wiring_diagram`, `has_program_archive`, `has_test_report`, `has_ul_label_photo` — set to `false` and `completeness_pct` at `0`. A `DesignEngineer` updates the flags via the package's update action; each flag transition recomputes the completeness percentage. The update action accepts flag writes while the package is in any status (including `APPROVED` and `RELEASED`); the PATCH itself increments the package's `version`, and an auto-transition triggered by the recompute increments it again. Flag writes performed as side effects of other transitions — test completion setting `has_test_report`, label affixing setting `has_ul_label_photo` — do not by themselves increment the package's `version`; only a resulting auto-transition does. The percentage is a weighted score: the wiring diagram contributes `0.35`, the program archive contributes `0.25`, the test report contributes `0.25`, and the UL label photo contributes `0.15`; the weighted sum is multiplied by `100` and rounded half-up to an integer percent in `[0, 100]`. The package begins in `INCOMPLETE`. When `completeness_pct` reaches `100`, the package auto-transitions `INCOMPLETE → PENDING_REVIEW`. Conversely, if any flag later flips from `true` back to `false` while the package is in `PENDING_REVIEW` — a document withdrawal — the package regresses `PENDING_REVIEW → INCOMPLETE`. Both auto-transitions increment the package's `version` by one.

In `PENDING_REVIEW`, a `QAManager` whose id differs from the panel's `design_engineer_id` approves the package, transitioning to `APPROVED`; a self-approval is rejected with `ERR_SEGREGATION_OF_DUTIES`. The same `QAManager` may instead return the package for rework, transitioning back to `INCOMPLETE`. Finally, a `ProjectManager` releases an `APPROVED` package, transitioning to terminal `RELEASED` — but only when the owning panel's status is in `{TEST_PASSED, READY_FOR_LABEL, LABELED}`; a release attempt against a panel in any other state is rejected with `ERR_INVALID_STATE` (HTTP 409). Release increments the package's `version` and re-evaluates the job posture, because the job's `READY_TO_SHIP` gate requires every panel's as-built package to be `RELEASED`.

### 3.7. Startup Support: Scheduled Windows, Remote Access, and Labor Billing

Once a panel is `SHIPPED`, the customer expects startup support. A `ProjectManager` schedules a `StartupSession` for the panel by supplying `scheduled_start` and `scheduled_end` (both UTC, with `scheduled_end` strictly after `scheduled_start`), the `engineer_id` of the `FieldEngineer` who will perform the work, and optionally `support_mode` (one of `ONSITE` or `REMOTE`, defaulting to `ONSITE`) and `remote_access_granted` (defaulting to `false`). Two temporal guards run at scheduling time. First, the engineer's calendar: no two sessions in `SCHEDULED` or `IN_PROGRESS` for the same `engineer_id` may have overlapping half-open `[scheduled_start, scheduled_end)` windows — adjacency, where one session's `scheduled_end` equals another's `scheduled_start`, is permitted — and a violation is rejected with `ERR_ENGINEER_DOUBLE_BOOKED` (HTTP 422). Second, the panel turnover buffer: a new session for the same panel must not begin within 24 hours after the `scheduled_end` of any other `SCHEDULED` or `IN_PROGRESS` session for that panel; the rule uses buffer-inflated interval semantics, so a gap of at least 24 hours is required and a gap of exactly 24 hours is permitted, with violations rejected with `ERR_PANEL_TURNOVER_VIOLATION` (HTTP 422). Additionally, choosing `support_mode` of `REMOTE` requires `remote_access_granted` to be `true`; a remote session without the customer's grant is rejected with `ERR_REMOTE_ACCESS_REQUIRED` (HTTP 422). Scheduling is not gated on the panel's current status — only beginning the work requires the panel to be `SHIPPED` — and the window is not compared against the current logical clock, so a window lying entirely in the past is accepted at scheduling time (the no-show sweep will retire it). The new session serializes `labor_hours` as `0` and `billable_cents` as null until completion.

The new session begins in `SCHEDULED`. A `FieldEngineer` begins the work only when the current logical clock is at or after `scheduled_start` and at or before `scheduled_end`, when the owning panel is in `SHIPPED`, and — when `support_mode` is `REMOTE` — when `remote_access_granted` is `true`. A begin attempt outside the window is rejected with `ERR_OUTSIDE_SCHEDULED_WINDOW` (HTTP 422); a remote begin without the grant is rejected with `ERR_REMOTE_ACCESS_REQUIRED`; a begin against a panel that is not `SHIPPED` is rejected with `ERR_INVALID_STATE`. A successful begin transitions `SCHEDULED → IN_PROGRESS` and increments the session's `version`.

If the logical clock advances past `scheduled_end` while the session is still `SCHEDULED`, the system auto-transitions it to `NO_SHOW` and increments its `version`. A `ProjectManager` may also cancel a `SCHEDULED` session outright, transitioning to `CANCELLED`.

Completion is the commissioning event. A `FieldEngineer` completes an `IN_PROGRESS` session by supplying the actual `labor_hours` worked, which must be greater than zero. Completion requires that the owning panel have a `RELEASED` `ProgramVersion` with `site_backup_taken` equal to `true`; without that evidence the complete is rejected with `ERR_BACKUP_REQUIRED`. On a successful complete, the session transitions `IN_PROGRESS → COMPLETED`, the panel auto-transitions `SHIPPED → COMMISSIONED` with `commissioned_at` set to the current time, the job posture is re-evaluated (so the last-commissioned panel may push the job itself into `COMMISSIONED` and set `warranty_expires_at`), the startup labor billing is computed and stored on the session as `billable_cents`, and the session's `version` increments. The `billable_cents` figure is billed separately from the job ledger and does not touch `approved_co_delta_cents`.

Startup labor billing is a waterfall over the supplied `labor_hours`. The first `8` hours are billed at a base rate of `18533` cents per hour. Hours beyond `8` and up to a total of `16` hours are overtime, billed at one-and-a-half times the base rate; the overtime rate is computed by multiplying the base rate by `1.5` and rounding half-up to integer cents first, and only then multiplying by the number of overtime hours — the rounding order is pinned, so the per-hour overtime rate is `27800` cents regardless of how many overtime hours are billed. Hours beyond `16` are emergency hours, billed at exactly twice the base rate. The raw bill is the sum of the base, overtime, and emergency components. When `scheduled_start` falls on a Saturday or Sunday (UTC), the raw bill is multiplied by `1.25`; the final `billable_cents` is that product rounded half-up to integer cents. On a weekday the multiplier is `1` and the bill is the raw sum rounded half-up. While the session is not yet `COMPLETED`, `billable_cents` is null.

### 3.8. Change Orders, the Contract Ledger, and Supersede-on-Approve

Scope creep is handled through `ChangeOrder`s against the job's contract ledger. A `ProjectManager` drafts a change order by supplying a free-text `description`, a signed `price_delta_cents` (positive means the customer pays more), and optionally a `discount_pct` in the closed range `[0, 0.5]` defaulting to `0`. The server assigns a monotonic `co_number` within the job (the first is `1`, the next `2`, and so on — ordering is by `co_number`, never by `id`), records the acting `ProjectManager`'s id as `requested_by_id`, computes `computed_delta_cents` via the pricing rule below, and starts the order in `PROPOSED`. Drafting is not gated on the job's current status. A missing `price_delta_cents` or an out-of-range `discount_pct` is rejected with `ERR_INVALID_REQUEST`.

Change-order pricing pins an evaluation order that would otherwise be circular. The volume-discount tier is keyed on the order's pre-discount `price_delta_cents`: below `100000` cents the tier is `T0`, from `100000` up to but not including `500000` cents the tier is `T1`, and `500000` cents or more the tier is `T2`. The effective discount is the maximum of the supplied `discount_pct` and the tier floor — `0.00` for `T0`, `0.05` for `T1`, `0.10` for `T2`. When `price_delta_cents` is non-negative, `computed_delta_cents` is the price delta multiplied by one minus the effective discount, rounded half-up to integer cents. When `price_delta_cents` is negative — a credit back to the customer — the credit passes through undiscounted: `computed_delta_cents` equals `price_delta_cents` exactly, because a discount never deepens a credit. Rounding happens exactly once at the multiplication step; there is no double rounding.

The customer counter-offers via the revise action, which the owning `Customer` performs against a `PROPOSED` order with a new `price_delta_cents` and optionally a new `discount_pct` (when `discount_pct` is omitted, the order's existing value is kept); revise recomputes `computed_delta_cents` and increments the order's `version`. The `ProjectManager` accepts the counter by re-proposing, transitioning `REVISED → PROPOSED` and incrementing the version. Either side may end the loop: the `Customer` rejects a `PROPOSED` or `REVISED` order (terminal `REJECTED`), and the `ProjectManager` whose id matches `requested_by_id` withdraws a `PROPOSED` order (terminal `WITHDRAWN`).

Approval is the ledger-critical step and is guarded by optimistic concurrency. The owning `Customer` approves a `PROPOSED` or `REVISED` order by supplying `expected_job_version`, which must equal the job's current `version`; a stale value is rejected with `ERR_STALE_VERSION`. Approval is further gated on the customer's `credit_hold` being `false` (else `ERR_CREDIT_HOLD`) and on the job not being `CLOSED` (else `ERR_INVALID_STATE`). On a successful approval, the order's `computed_delta_cents` is added to the job's `approved_co_delta_cents`, the job's `contract_price_cents` is recomputed as `quoted_price_cents` plus `approved_co_delta_cents`, the job's `version` increments by one (it is the OCC anchor), the order's `version` increments by one, and the order transitions to `APPROVED`. Approval optionally names a `supersedes_co_id`: when supplied, the referenced order — which must belong to the same job and be in `PROPOSED` or `REVISED` — transitions to `SUPERSEDED`. The `supersedes_co_id` reference is validated (well-formed, existing, same-job, in a supersede-able state) before the order's own state and OCC checks run; the approved order's own `supersedes_co_id` field records the reference, and the superseded order's `version` increments by one. A `Job` read exposes `contract_price_cents` directly so a client can always see the current ledger.

Approval is not irreversible. A `ProjectManager` rescinds an `APPROVED` order by supplying `expected_job_version`, again validated against the job's current `version` with `ERR_STALE_VERSION` on a mismatch. Rescind requires the job to not be `CLOSED`. On success, the order's `computed_delta_cents` is subtracted from the job's `approved_co_delta_cents` as a compensating entry, `contract_price_cents` is recomputed, the job's `version` increments, the order transitions `APPROVED → SUPERSEDED`, and the order's `version` increments.

### 3.9. Warranty Claims and the Provisional-to-Final Liability Ledger

The control-logic warranty runs from the moment a job commissions. A `Customer` files a `WarrantyClaim` against a job by supplying the implicated `panel_id`, a free-text `defect_description`, and `claimed_labor_hours` (which must be at least zero). The `panel_id` must reference an existing panel (else `ERR_REFERENCE_NOT_FOUND`) but is not required to belong to the job the claim is filed against. Filing sets `filed_at` to the current logical time. Admissibility is checked at filing: the job must have at least one `COMMISSIONED` panel and `claimed_labor_hours` must be non-negative; violations are rejected with `ERR_CLAIM_INADMISSIBLE` (HTTP 422). Filing or later triaging against a job whose `warranty_expires_at` is null (not yet commissioned) or already past is rejected with `ERR_WARRANTY_EXPIRED` (HTTP 422); concretely, `filed_at` must be less than or equal to `warranty_expires_at`. The new claim starts in `FILED`.

A `QAManager` triages a `FILED` claim, transitioning it to `TRIAGED`. Triage re-checks the admissibility window against the current logical time at the moment of triage — not against the claim's recorded `filed_at` — so a claim filed inside the window but triaged after expiry is rejected with `ERR_WARRANTY_EXPIRED`; concretely, triage requires the triage-time logical clock to be less than or equal to `warranty_expires_at`, with the same null-expiry rule as at filing. Triage then records `provisional_liability_cents` computed by the provisional variant of the warranty-liability rule; the claim's `version` increments.

From `TRIAGED` the claim is adjudicated. Acceptance by the `QAManager` computes `final_liability_cents` using the final variant of the warranty-liability rule, writes `liability_delta_cents` as the final liability minus the provisional liability — the reconciliation entry for the accrual ledger — and transitions the claim to `ACCEPTED`. Denial computes `final_liability_cents` as zero and writes `liability_delta_cents` as the negation of the provisional liability (a compensating reversal), transitioning the claim to `DENIED`. Both adjudications increment the claim's `version`. A `ProjectManager` settles an `ACCEPTED` claim (terminal `SETTLED`) or closes a `DENIED` claim (terminal `CLOSED`).

The warranty-liability calculation takes the claim's `claimed_labor_hours`, the claim's `filed_at`, the parent job's `warranty_months`, the owning customer's `warranty_labor_tier`, and the latest `commissioned_at` across the job's `COMMISSIONED` panels as inputs. Months in service is the integer floor of the number of days between `filed_at` and that latest `commissioned_at` divided by `30`. The base labor rate is selected by tier: `9500` cents per hour for `TIER_LOCAL`, `14500` cents per hour for `TIER_REGIONAL`, and `21000` cents per hour for `TIER_NATIONAL`. Labor is the claimed hours multiplied by the tier rate, rounded half-up to integer cents. A flat diagnostic parts allowance of `25000` cents is added. The subtotal is labor plus parts.

The two variants differ in what they apply on top of the subtotal. The **provisional variant**, used at triage, is a conservative worst-case accrual: liability is the minimum of the subtotal and a cap of `500000` cents; no age-decay halving and no deductible subtraction are applied. The **final variant**, used at acceptance, applies both adjustments: first, if twice the months in service exceeds the job's `warranty_months` — that is, the claim was filed after half the warranty term has elapsed — the labor component is halved (rounded half-up to integer cents) and the subtotal is recomputed as halved labor plus the parts allowance; then the liability is the minimum of that subtotal and the `500000`-cent cap; finally the customer absorbs the first `10000` cents of every adjudicated claim, so the deductible is subtracted from the liability with the result floored at zero. The same constants — the three tier rates, the `500000`-cent cap, the `10000`-cent deductible, and the `25000`-cent parts allowance — govern both variants; only the halving and the deductible differ.

## 4. Endpoint Definitions

All endpoints are mounted under `/panel-shop`, except the test-driving logical-clock endpoint, which is mounted at the root as `/_clock/set_current_utc`. Successful resource creation returns HTTP `201`; successful modifications, state transitions, and reads return HTTP `200`. Error responses carry the HTTP status catalogued in §5 next to the matching `error_id`. Request and response payloads are not tabulated here; readers reconstruct them from §3 narratives and §2.4's common resource properties. Beyond the filters named in the table, the nested list endpoints accept a `status` query filter wherever the listed resource carries a `status` field (`/jobs/{id}/change-orders`, `/jobs/{id}/warranty-claims`, `/panels/{id}/substitution-requests`, `/panels/{id}/test-sessions`, `/panels/{id}/startup-sessions`, `/panels/{id}/program-versions`); `/panels/{id}/test-points` additionally accepts a `result` filter and `/panels/{id}/components` a `line_status` filter.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the server's logical clock; advancing past a `scheduled_end` fires the no-show sweep. | ProjectManager, QAManager |
| POST | `/panel-shop/customers` | Register a customer. | ProjectManager |
| GET | `/panel-shop/customers/{id}` | Fetch one customer. | ProjectManager, QAManager, DesignEngineer, Customer, ShopLead, TestTechnician, ControlsEngineer, FieldEngineer, ShippingClerk |
| GET | `/panel-shop/customers` | List customers with pagination. | ProjectManager, QAManager |
| PATCH | `/panel-shop/customers/{id}` | Update `credit_hold` or `warranty_labor_tier`. | ProjectManager |
| GET | `/panel-shop/customers/{id}/jobs` | List jobs of a customer. | ProjectManager, QAManager, Customer |
| POST | `/panel-shop/jobs` | Create a panel-build job for a customer. | ProjectManager |
| GET | `/panel-shop/jobs/{id}` | Fetch a job with computed `contract_price_cents`. | ProjectManager, QAManager, Customer, DesignEngineer, ShopLead |
| GET | `/panel-shop/jobs` | List jobs with optional `customer_id` and `status` filters. | ProjectManager, QAManager, Customer |
| POST | `/panel-shop/jobs/{id}/advance` | Manual advance `OPEN → DESIGN`. | ProjectManager |
| POST | `/panel-shop/jobs/{id}/hold` | Put a mid-flight job `ON_HOLD`. | ProjectManager |
| POST | `/panel-shop/jobs/{id}/resume` | Resume from `ON_HOLD`; posture engine re-derives status. | ProjectManager |
| POST | `/panel-shop/jobs/{id}/ship` | Ship all eligible panels; job `READY_TO_SHIP → SHIPPED`. | ShippingClerk |
| POST | `/panel-shop/jobs/{id}/close` | Close a commissioned job. | ProjectManager |
| GET | `/panel-shop/jobs/{id}/panels` | List panels of a job. | ProjectManager, QAManager, DesignEngineer, ShopLead, TestTechnician, Customer |
| GET | `/panel-shop/jobs/{id}/change-orders` | List change orders of a job. | ProjectManager, QAManager, Customer |
| GET | `/panel-shop/jobs/{id}/warranty-claims` | List warranty claims of a job. | ProjectManager, QAManager, Customer |
| POST | `/panel-shop/jobs/{job_id}/panels` | Create a panel under a job; auto-advances job `OPEN → DESIGN` when first panel. | DesignEngineer |
| GET | `/panel-shop/panels/{id}` | Fetch a panel. | ProjectManager, QAManager, DesignEngineer, ShopLead, TestTechnician, ControlsEngineer, FieldEngineer, Customer, ShippingClerk |
| GET | `/panel-shop/panels` | List panels with `job_id` and `status` filters. | ProjectManager, QAManager, DesignEngineer, ShopLead |
| POST | `/panel-shop/panels/{id}/submit-review` | Panel `DESIGN → DESIGN_REVIEW`. | DesignEngineer |
| POST | `/panel-shop/panels/{id}/approve-design` | Panel `DESIGN_REVIEW → DESIGN_APPROVED` (SoD: approver != designer). | QAManager |
| POST | `/panel-shop/panels/{id}/reject-design` | Panel `DESIGN_REVIEW → DESIGN` (revision loop). | QAManager |
| POST | `/panel-shop/panels/{id}/release-procurement` | Panel `DESIGN_APPROVED → PROCUREMENT`; BOM lines `PENDING → ORDERED`. | ProjectManager |
| POST | `/panel-shop/panels/{id}/start-wiring` | Panel `PROCUREMENT → WIRING` (requires all lines received/substituted). | ShopLead |
| POST | `/panel-shop/panels/{id}/begin-test` | Panel `WIRING → POINT_TO_POINT`. | ShopLead |
| POST | `/panel-shop/panels/{id}/rework` | Panel `TEST_FAILED → WIRING`; resets test points to `UNTESTED`. | ShopLead |
| POST | `/panel-shop/panels/{id}/request-label` | Panel `TEST_PASSED → READY_FOR_LABEL`. | QAManager |
| POST | `/panel-shop/panels/{id}/affix-label` | Panel `READY_FOR_LABEL → LABELED`; mints `label_serial`. | QAManager |
| POST | `/panel-shop/panels/{id}/components` | Add a BOM line to a panel. | DesignEngineer |
| GET | `/panel-shop/panels/{id}/components` | List BOM lines of a panel. | ProjectManager, QAManager, DesignEngineer, ShopLead |
| GET | `/panel-shop/panel-components/{id}` | Fetch one BOM line. | ProjectManager, QAManager, DesignEngineer, ShopLead |
| GET | `/panel-shop/panel-components` | List BOM lines across panels with `panel_id`, `component_id`, `substituted_for_id`, `line_status` filters. | ProjectManager, QAManager, DesignEngineer, ShopLead |
| GET | `/panel-shop/components/{id}/panel-components` | List BOM lines referencing a catalog component. | ProjectManager, QAManager, DesignEngineer, ShopLead |
| PATCH | `/panel-shop/panel-components/{id}` | Change `quantity` of a `PENDING` line. | DesignEngineer |
| POST | `/panel-shop/panel-components/{id}/receive` | Mark an `ORDERED` line `RECEIVED`. | ShopLead |
| POST | `/panel-shop/components` | Register a catalog component. | QAManager |
| GET | `/panel-shop/components/{id}` | Fetch a component. | ProjectManager, QAManager, DesignEngineer, ShopLead |
| GET | `/panel-shop/components` | List catalog with `component_class` and `active` filters. | ProjectManager, QAManager, DesignEngineer, ShopLead |
| PATCH | `/panel-shop/components/{id}` | Update `lead_time_days`, `unit_cost_cents`, or `active`. | QAManager |
| POST | `/panel-shop/panels/{id}/substitution-requests` | Request a component substitution for a BOM line. | DesignEngineer |
| GET | `/panel-shop/substitution-requests/{id}` | Fetch a substitution request. | ProjectManager, QAManager, DesignEngineer, Customer |
| GET | `/panel-shop/panels/{id}/substitution-requests` | List substitution requests of a panel. | ProjectManager, QAManager, DesignEngineer, Customer |
| GET | `/panel-shop/substitution-requests` | List substitution requests across panels with `panel_id`, `original_line_id`, `proposed_component_id`, `status` filters. | ProjectManager, QAManager, DesignEngineer, Customer |
| POST | `/panel-shop/substitution-requests/{id}/counter` | Customer counters the request (`REQUESTED → COUNTERED`). | Customer |
| POST | `/panel-shop/substitution-requests/{id}/resubmit` | Engineer resubmits a countered request (`COUNTERED → REQUESTED`). | DesignEngineer |
| POST | `/panel-shop/substitution-requests/{id}/approve` | QA approves; swaps BOM line; recomputes SCCR and lead-time delta. | QAManager |
| POST | `/panel-shop/substitution-requests/{id}/reject` | QA rejects (`REQUESTED → REJECTED`). | QAManager |
| POST | `/panel-shop/substitution-requests/{id}/withdraw` | Requester withdraws (`REQUESTED → WITHDRAWN`). | DesignEngineer |
| POST | `/panel-shop/panels/{id}/test-points` | Add a test point to the panel's test plan. | DesignEngineer |
| GET | `/panel-shop/panels/{id}/test-points` | List test points of a panel. | ProjectManager, QAManager, DesignEngineer, TestTechnician, ShopLead |
| POST | `/panel-shop/panels/{id}/test-sessions` | Open a test session on a `POINT_TO_POINT` panel. | TestTechnician |
| GET | `/panel-shop/test-sessions/{id}` | Fetch a test session. | ProjectManager, QAManager, TestTechnician, ShopLead |
| GET | `/panel-shop/panels/{id}/test-sessions` | List test sessions of a panel. | ProjectManager, QAManager, TestTechnician, ShopLead |
| POST | `/panel-shop/test-sessions/{id}/record-result` | Record `PASS`/`FAIL`/`SKIPPED` for one `UNTESTED` point. | TestTechnician |
| POST | `/panel-shop/test-sessions/{id}/complete` | Complete a session; fires panel auto-transition. | TestTechnician |
| POST | `/panel-shop/test-sessions/{id}/abort` | Abort; wipes recorded results of this session. | TestTechnician |
| POST | `/panel-shop/panels/{panel_id}/program-versions` | Create a `ProgramVersion` with immediate release (OCC on `Panel.version`). | ControlsEngineer |
| GET | `/panel-shop/program-versions/{id}` | Fetch a program version. | ProjectManager, QAManager, ControlsEngineer, FieldEngineer, DesignEngineer |
| GET | `/panel-shop/panels/{id}/program-versions` | List program versions of a panel. | ProjectManager, QAManager, ControlsEngineer, FieldEngineer, DesignEngineer |
| POST | `/panel-shop/program-versions/{id}/archive` | Archive a `DRAFT` or `SUPERSEDED` version. | ControlsEngineer |
| POST | `/panel-shop/program-versions/{id}/mark-site-backup` | Mark `site_backup_taken` on a `RELEASED` version. | FieldEngineer |
| POST | `/panel-shop/panels/{panel_id}/startup-sessions` | Schedule a startup window for a panel. | ProjectManager |
| GET | `/panel-shop/startup-sessions/{id}` | Fetch a startup session. | ProjectManager, QAManager, FieldEngineer, Customer |
| GET | `/panel-shop/panels/{id}/startup-sessions` | List startup sessions of a panel. | ProjectManager, QAManager, FieldEngineer, Customer |
| POST | `/panel-shop/startup-sessions/{id}/start` | Begin an in-window session (`SCHEDULED → IN_PROGRESS`). | FieldEngineer |
| POST | `/panel-shop/startup-sessions/{id}/complete` | Complete with `labor_hours`; cascades panel `SHIPPED → COMMISSIONED`. | FieldEngineer |
| POST | `/panel-shop/startup-sessions/{id}/cancel` | Cancel a `SCHEDULED` session. | ProjectManager |
| POST | `/panel-shop/jobs/{id}/change-orders` | Draft a change order (`PROPOSED`). | ProjectManager |
| GET | `/panel-shop/change-orders/{id}` | Fetch a change order. | ProjectManager, QAManager, Customer |
| GET | `/panel-shop/change-orders` | List change orders across jobs with `job_id`, `supersedes_co_id`, `status` filters. | ProjectManager, QAManager, Customer |
| POST | `/panel-shop/change-orders/{id}/revise` | Customer counter-offer (`PROPOSED → REVISED`). | Customer |
| POST | `/panel-shop/change-orders/{id}/repropose` | PM re-tables a revised order (`REVISED → PROPOSED`). | ProjectManager |
| POST | `/panel-shop/change-orders/{id}/approve` | Customer approves with OCC on `Job.version`; posts to ledger. | Customer |
| POST | `/panel-shop/change-orders/{id}/reject` | Customer rejects. | Customer |
| POST | `/panel-shop/change-orders/{id}/withdraw` | Drafting PM withdraws. | ProjectManager |
| POST | `/panel-shop/change-orders/{id}/rescind` | Compensating reversal of an `APPROVED` order (OCC on `Job.version`). | ProjectManager |
| POST | `/panel-shop/jobs/{id}/warranty-claims` | File a control-logic warranty claim. | Customer |
| GET | `/panel-shop/warranty-claims/{id}` | Fetch a warranty claim. | ProjectManager, QAManager, Customer |
| GET | `/panel-shop/warranty-claims` | List warranty claims across jobs with `job_id`, `panel_id`, `status` filters. | ProjectManager, QAManager, Customer |
| POST | `/panel-shop/warranty-claims/{id}/triage` | QA triage; computes `provisional_liability_cents`. | QAManager |
| POST | `/panel-shop/warranty-claims/{id}/accept` | QA accepts; computes `final_liability_cents` and `liability_delta_cents`. | QAManager |
| POST | `/panel-shop/warranty-claims/{id}/deny` | QA denies; reverses provisional accrual. | QAManager |
| POST | `/panel-shop/warranty-claims/{id}/settle` | PM settles an accepted claim. | ProjectManager |
| POST | `/panel-shop/warranty-claims/{id}/close` | PM closes a denied claim. | ProjectManager |
| GET | `/panel-shop/as-built-packages/{id}` | Fetch an as-built package. | ProjectManager, QAManager, DesignEngineer, Customer |
| GET | `/panel-shop/panels/{id}/as-built-packages` | Fetch the as-built package of a panel (1:1, returns array of 0–1). | ProjectManager, QAManager, DesignEngineer, Customer |
| PATCH | `/panel-shop/as-built-packages/{id}` | Upload or withdraw document flags; recomputes `completeness_pct`. | DesignEngineer |
| POST | `/panel-shop/as-built-packages/{id}/approve` | QA approves a complete package (`PENDING_REVIEW → APPROVED`). | QAManager |
| POST | `/panel-shop/as-built-packages/{id}/return-for-rework` | QA returns a package (`PENDING_REVIEW → INCOMPLETE`). | QAManager |
| POST | `/panel-shop/as-built-packages/{id}/release` | PM releases an approved package (`APPROVED → RELEASED`). | ProjectManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_SCCR_BELOW_MINIMUM` | 422 |
| `ERR_SUBSTITUTION_DOWNRATED` | 422 |
| `ERR_OUTSIDE_SCHEDULED_WINDOW` | 422 |
| `ERR_WARRANTY_EXPIRED` | 422 |
| `ERR_ENGINEER_DOUBLE_BOOKED` | 422 |
| `ERR_PANEL_TURNOVER_VIOLATION` | 422 |
| `ERR_COMPONENT_INACTIVE` | 422 |
| `ERR_DUPLICATE` | 409 |
| `ERR_CREDIT_HOLD` | 402 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_CLAIM_INADMISSIBLE` | 422 |
| `ERR_REMOTE_ACCESS_REQUIRED` | 422 |
| `ERR_TEST_POINTS_UNDECIDED` | 422 |
| `ERR_PANEL_NOT_READY` | 409 |
| `ERR_JOB_GATE_BLOCKED` | 409 |
| `ERR_BACKUP_REQUIRED` | 422 |
| `ERR_INVALID_REQUEST_BODY` | 400 |

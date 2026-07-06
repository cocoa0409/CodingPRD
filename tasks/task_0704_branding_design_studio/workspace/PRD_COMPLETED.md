# Branding & Design Studio API — Product Requirements Document

## 1. Introduction

A branding and design studio runs creative engagements that are simultaneously artistic and financial: a client commissions a logo, an identity system, or a website; designers build moodboards and concept routes; revision rounds are negotiated and sometimes paid for; assets are delivered, accepted, and handed off; and money moves through deposits, milestone invoices, pass-through stock and font licenses, change orders, and ongoing care-plan retainers. This document specifies the API that orchestrates that full engagement, holding the creative workflow and the billing ledger in lockstep so that neither can drift out of agreement with the other.

The system treats a **Project** as the spine of an engagement. A project advances through discrete lifecycle stages, and several of those advances are gated on the state of its child artifacts — a project cannot leave discovery until a moodboard is approved, cannot leave the concept phase until a concept route is approved, and cannot be handed off until every required deliverable is accepted and the agreed deposit has been collected. Layered over this creative pipeline is a money model with two distinct flavors of deposit (a provisional figure locked at activation and a final figure that tracks approved scope changes), tiered late fees on overdue invoices, marked-up license pass-throughs, and tiered overage billing on retainer care cycles. Because scope changes mutate the financial picture of a live project, change-order creation is guarded by optimistic concurrency so that a client proposing a new amount is always working from the ledger it last observed.

This specification is written for the engineers implementing the service. It is organized so that Section 2 fixes the system-wide contracts — authentication, the response envelope, pagination, money precision, concurrency, and cascade consistency — while Section 3 narrates the business workflows in the order an engagement naturally unfolds. Sections 4 and 5 summarize the HTTP surface and the error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply across the entire API. All resources are mounted under the studio root path `/studios`.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers. The `X-User-ID` header identifies the acting user, and the `X-User-Role` header declares the operational capacity under which the request is made. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`.

The system recognizes exactly four roles: `StudioOps`, `Designer`, `Client`, and `BillingOps`. `StudioOps` is the studio operator who manages projects, scope, milestones, licenses, retainers, change-order proposals, and stage advancement. `Designer` is the creative producer who authors moodboards, concepts, and deliverables and presents them for review. `Client` is the commissioning party who approves or rejects moodboards, concepts, deliverables, and change orders, and who requests revisions. `BillingOps` is the billing operator who issues and pays invoices, marks invoices overdue, records deposits, and bills care cycles. When an authenticated caller invokes an operation its role is not permitted to perform, the request is rejected with `ERR_UNAUTHORIZED`.

Three of the four roles are **opaque operator identities**. When `X-User-Role` is `StudioOps`, `Designer`, or `BillingOps`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The `Client` role, by contrast, is **entity-backed**: when `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client` record. Ownership checks on any resource that references a client compare that resource's owning `client_id` (resolved through the project the resource belongs to) against `X-User-ID`; a `Client` acting on a project, moodboard, concept, deliverable, or change order that does not trace back to its own `client_id` is rejected with `ERR_UNAUTHORIZED`. On studio-wide collection (list) endpoints that are not scoped to a single owning project — listing projects, invoices, change orders, or retainers — a `Client` is never rejected on ownership grounds but instead receives only the resources tracing back to its own `client_id`, with resources belonging to other clients silently filtered out of the page.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, and it must be at least 1 and no more than 100. The `offset` parameter sets the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

List-based responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every persisted resource — studios, clients, projects, moodboards, concepts, milestones, invoices, deliverables, licenses, change orders, retainers, and care cycles — carries a system-generated `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed in ISO 8601 UTC with three fractional digits, recording when the resource was first created.

Every entity in this system is also a mutable resource and therefore additionally carries an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) refreshed on every change, and a `version` integer that begins at `1` on creation and increments by one on every mutation of the resource. Updates to computed ledger fields — for example recomputing a project's `contract_value_cents` or `final_deposit_cents` — are themselves mutations: they refresh `updated_at` and increment the owning resource's `version`. The `version` integer is what optimistic concurrency control reads, as described in §2.7.

### 2.5. The Money Model: Cents, Precision, and Rounding

All monetary quantities in this system are stored and exchanged as whole-cent integers; there are no fractional-cent values in any stored field or response body. Wherever a calculation produces a non-integer cent figure — applying a deposit percentage, a tax rate, a markup, or a late-fee rate — the result is converted to whole cents using **round half up** (a value exactly halfway between two whole cents rounds to the larger magnitude). Two configuration fields are exceptions to the integer-cents rule because they are fractions rather than amounts: a studio's `tax_rate` and `license_markup_pct` are stored as decimal fractions (for example a tax rate of `0.0825` or a markup of zero) and preserve their input precision.

Several rounding orders are deliberately pinned and must not be rearranged. Tax on an invoice is rounded once, on the credited taxable base, before any late fee is considered. A late fee is rounded once, on the net-before-fee figure. License markup is rounded **per line** — each license's billable amount is rounded to whole cents on its own before any project-level total sums those rounded line amounts together (round-per-line, then sum; never sum-then-round). Each of these orders is restated in the workflow that depends on it, in §3.

### 2.6. Dual-Variant Deposit Reconciliation

A project carries two computed deposit figures that share a formula but diverge over the life of the engagement, and the distinction between them is central to the billing model. The **provisional deposit**, stored in `provisional_deposit_cents`, is computed once at activation from the base scope and is then locked permanently — it is never recomputed, even after scope changes. The **final deposit**, stored in `final_deposit_cents`, is recomputed every time a change order is approved and is the figure read at delivery reconciliation to decide whether the deposit gate has been satisfied.

Concretely, the project also tracks `base_scope_cents` (the snapshot of milestone amounts taken at activation) and `contract_value_cents` (the base scope plus the net of all approved change-order deltas). While the two deposit figures are equal at activation, the final deposit diverges upward or downward from the provisional deposit the moment any change order is approved, because the final deposit follows `contract_value_cents` while the provisional deposit stays frozen on `base_scope_cents`. The precise formulas live with the project-activation and change-order narratives in §3.

### 2.7. Optimistic Concurrency Control on Change-Order Creation

Proposing a change order against a project is the one write in this system guarded by optimistic concurrency, because a change order alters the project's financial picture and must be proposed against a ledger the client has actually seen. A change-order creation request must carry an `expected_project_version` field whose value is the `version` of the target project as the client last observed it; this field is required, not optional. Before the change order is created, the server compares `expected_project_version` against the project's current `version`. If they do not match — which happens whenever any other write has advanced the project's `version` since the client last read it (most commonly another change-order approval, though recording a deposit, activation, every stage advance, completion, and cancellation each bump the `version` as well) — the creation is rejected with `ERR_STALE_PROJECT_VERSION` and HTTP status 412, and the client must re-read the project before proposing a new amount. No other endpoint in the system accepts or requires a version field; only change-order creation does.

### 2.8. Hierarchical Consistency and Cascades

The system keeps parents and children in agreement automatically. When a parent's lifecycle transition resolves or invalidates its children, the server performs the dependent state changes itself without requiring a separate client request on each child, and every such automatic mutation refreshes the affected resource's `updated_at` and increments its `version`. Two broad families of cascade exist: forward cascades that finalize children when an engagement progresses (for example, billing a project's licenses when it moves into handoff, and waiving zero-amount milestones at completion), and unwind cascades that reject or void children when a project is cancelled. Each cascade is described in full in the workflow that triggers it, in §3, including every entity it touches; an implementer should treat a missing cascade target as a bug, because the test suite asserts the complete set.

### 2.9. Nested Resource Retrieval and Path Validation

Many resources are addressed through nested paths that name a studio, then a project (or a retainer), then the leaf resource. For any such request the server validates the path identifiers left to right and rejects the first one that does not resolve to an existing resource within the enclosing scope, returning `ERR_NOT_FOUND`. A moodboard requested under a project that does not exist fails on the project before the moodboard is ever consulted; a care cycle requested under a non-existent retainer fails on the retainer first. The same left-to-right existence discipline applies to body-referenced resources: a `milestone_id`, `client_id`, `project_id`, or `concept_id` named in a request body that does not resolve also yields `ERR_NOT_FOUND`. Path existence is checked before the request body is examined for well-formedness, but a body-referenced identifier is resolved only after the body's required fields and value types have passed that well-formedness check — so when a single request both omits a required field and names a non-existent reference, the well-formedness `ERR_INVALID_REQUEST` surfaces first. Well-formedness is in turn checked before any state or business rule.

### 2.10. Interval Windows for Licenses and Care Cycles

Two kinds of resource carry time windows, and the windows of like resources on the same parent may not overlap. A license window is a **closed** interval running from `valid_from` to `valid_until` inclusive of both ends; two license windows on the same project overlap if they share any instant, and a creation that would overlap any existing license on the project — every license counts here regardless of its status, so even a `VOIDED` license still blocks an overlapping window — is rejected with `ERR_INTERVAL_OVERLAP`. A care cycle window is a **half-open** interval running from `period_start` inclusive to `period_end` exclusive; two care-cycle windows on the same retainer overlap if they share any instant in their half-open extents, and an overlapping creation is likewise rejected with `ERR_INTERVAL_OVERLAP`. Independently of overlap, a window whose start is not strictly before its end — a license with `valid_from` at or after `valid_until`, or a care cycle with `period_start` at or after `period_end` — is malformed and rejected with `ERR_INVALID_INTERVAL`. This malformed-interval check is applied before the overlap check, so a window that is simultaneously malformed and overlapping is rejected with `ERR_INVALID_INTERVAL`.

### 2.11. The Logical Clock

Time-sensitive decisions — whether an invoice is past due, whether a care cycle's period has ended — are made against a server logical clock rather than wall-clock time. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any clock-setting call it holds that default and never falls back to real time. An administrative capability lets an operator move the clock to a supplied instant via the `to_iso8601` field; this capability is available to `StudioOps` and `BillingOps` and exists so deadline and expiry behavior is deterministic under test.

### 2.12. Validation Ordering

When several checks could fire on one request, they are evaluated in a fixed priority order so the returned error is predictable. Authentication comes first: missing or unknown headers yield `ERR_UNAUTHENTICATED`. Authorization is next: a role not permitted for the operation yields `ERR_UNAUTHORIZED`; the entity-backed `Client` ownership check, however, can only run once the target resource has been resolved, so a `Client` aimed at a resource that does not exist receives `ERR_NOT_FOUND`, while one aimed at a resolved resource it does not own receives `ERR_UNAUTHORIZED`. Existence follows: any path-referenced resource that does not resolve yields `ERR_NOT_FOUND`, validated left to right through the path. Request well-formedness is then checked on mutating endpoints — a malformed body, a missing required field, an invalid enum member, or a numeric value outside its declared bounds yields `ERR_INVALID_REQUEST`; a body-referenced resource (a `milestone_id`, `client_id`, `project_id`, or `concept_id`) is resolved only after this well-formedness passes, still yielding `ERR_NOT_FOUND` when it does not resolve. Only after these gates do the resource-specific checks run: the change-order concurrency check (`ERR_STALE_PROJECT_VERSION`), then the generic "is this transition defined from the current state" check (`ERR_INVALID_STATE`), then cross-stage gating (`ERR_PROJECT_WRONG_STAGE`), then interval overlap (`ERR_INTERVAL_OVERLAP`), then the concept revision limit (`ERR_REVISION_LIMIT_REACHED`), then the sibling/child stage-advance gates (`ERR_MOODBOARD_NOT_APPROVED`, `ERR_NO_APPROVED_CONCEPT`, `ERR_DELIVERABLES_INCOMPLETE`, `ERR_OPEN_INVOICES`), and finally the deposit gate (`ERR_DEPOSIT_UNPAID`). Each of these conditions is described in the workflow it guards; the ordering above is what determines which error surfaces when more than one applies.

## 3. Business Logic & Workflows

### 3.1. Founding a Studio and Its Clients

An engagement begins with a tenant root. A `StudioOps` operator creates a **Studio** by supplying its display `name`, and optionally a `tax_rate` (the sales-tax fraction applied to the taxable base of milestone invoices, defaulting to a tax rate of zero) and a `license_markup_pct` (the markup fraction added to pass-through license costs when they are billed to the client, also defaulting to zero). These two studio-level rates are read later by the invoice and license calculations and are the only fractional, non-integer money fields in the system.

Under a studio, a `StudioOps` operator registers a **Client** by supplying its `company_name` and `contact_email`; the system records the owning `studio_id` from the path and sets the client's `status` to `ACTIVE`. A client may later be archived by a `StudioOps` operator, moving its `status` from `ACTIVE` to `ARCHIVED`. Clients of a studio can be listed (filterable by `studio_id`) and fetched individually. The client's `status` matters at project activation: a project may only be activated for a client that is currently `ACTIVE`.

### 3.2. The Project Spine: Draft, Scope, and Activation

A `StudioOps` operator opens a **Project** in `DRAFT` by naming the commissioning `client_id`, a `title`, a `service_type` of `LOGO`, `IDENTITY`, or `WEB`, and a `deposit_pct` — the fraction of contract value the client must put down before delivery. At creation the project records its parent `studio_id` from the path, sets `status` to `DRAFT`, and initializes `base_scope_cents`, `contract_value_cents`, and `deposit_collected_cents` to zero. The computed ledger fields `provisional_deposit_cents` and `final_deposit_cents` remain unset — present in the project response but serialized as `null` — until activation. A project can be fetched (its computed ledger fields are included in the response) and projects can be listed under a studio, optionally filtered by `client_id` or `studio_id`.

While a project is still in `DRAFT`, a `StudioOps` operator builds out its scope as a set of **Milestones**. Each milestone is created with a `name`, an `amount_cents` (the billable amount in cents, which must be zero or greater), and a `sequence_index` giving its order within the project, which must be unique among that project's milestones. A new milestone starts in `PENDING`. Milestones can be listed and fetched per project.

Activation is the hinge of the whole engagement. A `StudioOps` operator activates a project, advancing it from `DRAFT` to `DISCOVERY`. Activation is refused unless the project has at least one milestone — otherwise `ERR_NO_MILESTONES` — and unless its `client_id` references a client whose `status` is `ACTIVE` — otherwise `ERR_CLIENT_NOT_ACTIVE`. On a successful activation the server snapshots the money model: `base_scope_cents` becomes the sum of the `amount_cents` of every milestone on the project; `contract_value_cents` is set equal to `base_scope_cents`, since no change order has been approved yet; `provisional_deposit_cents` is set to the base scope multiplied by the project's `deposit_pct`, rounded half up to whole cents, and is then **locked** for the life of the project and never recomputed; and `final_deposit_cents` is set to `contract_value_cents` multiplied by `deposit_pct`, rounded half up to whole cents. At activation the provisional and final deposits are therefore equal; they diverge only once change orders are approved.

Recording a deposit is a billing action. A `BillingOps` operator records a deposit cash payment of `amount_cents` (a non-negative integer) against the project, which adds that amount to the running `deposit_collected_cents`. There is no separate deposit entity; the call returns the updated project resource (carrying the incremented `deposit_collected_cents` and a bumped `version`) with HTTP 201. The accumulated deposit is what the handoff gate later checks against the final deposit.

A `StudioOps` operator may cancel a project only while it is in `DRAFT`, `DISCOVERY`, or `CONCEPT`; cancel has no defined transition from any other stage — `DELIVERY`, `HANDOFF`, or a terminal state (`COMPLETED`, `CANCELLED`) — and an attempt from any of those is rejected with `ERR_INVALID_STATE`. Cancellation from `DRAFT` simply moves the project to `CANCELLED` with no children to unwind. Cancellation from `DISCOVERY` or `CONCEPT` moves the project to `CANCELLED` and runs the unwind cascade described in §3.9.

### 3.3. Discovery: Moodboards

Once a project is in `DISCOVERY`, the creative discovery phase runs through **Moodboards**. A `Designer` creates a moodboard under the project with a `title`; it begins in `DRAFT`. Moodboards can be listed and fetched per project.

A `Designer` submits a moodboard for client review, moving it from `DRAFT` to `SUBMITTED`; the same submit action also returns a previously `REJECTED` moodboard to `SUBMITTED` for another look. Submission is allowed only while the parent project is in `DISCOVERY`; attempting it in any other project stage is rejected with `ERR_PROJECT_WRONG_STAGE`. The `Client` then reviews a submitted moodboard: approving it moves it from `SUBMITTED` to `APPROVED`, and approval is likewise gated on the parent project being in `DISCOVERY` (otherwise `ERR_PROJECT_WRONG_STAGE`). Rejecting a submitted moodboard moves it from `SUBMITTED` to `REJECTED`; rejection carries no project-stage precondition. The `APPROVED` state is terminal for a moodboard.

A project leaves discovery by advancing from `DISCOVERY` to `CONCEPT`, performed by a `StudioOps` operator. This advance is permitted only when at least one moodboard on the project has reached `APPROVED`; if none has, the advance is rejected with `ERR_MOODBOARD_NOT_APPROVED`.

### 3.4. Concept Rounds and the Revision Economy

With the project in `CONCEPT`, a `Designer` authors one or more **Concept** routes, each created with a `label` such as a route name, and an optional `revision_limit` capping the number of paid-for revision rounds before overage applies (defaulting to three). A new concept starts in `DRAFT` with its `rounds_used` counter at zero. Concepts can be listed and fetched per project.

The review of a concept is a cycle, and it is where the revision economy lives. A `Designer` presents a concept, moving it from `DRAFT` to `PRESENTED`; presentation is allowed only while the parent project is in `CONCEPT`, otherwise `ERR_PROJECT_WRONG_STAGE`. From `PRESENTED` the `Client` has three moves. The client may approve, moving the concept from `PRESENTED` to `APPROVED` — a terminal state — which makes the parent project eligible to advance out of the concept phase. The client may reject, moving the concept from `PRESENTED` to `REJECTED`, also terminal. Or the client may request a revision, moving the concept from `PRESENTED` to `IN_REVISION`; the designer answers a revision by presenting again, moving the concept from `IN_REVISION` back to `PRESENTED` (again only while the project is in `CONCEPT`). This presented–revision loop is the cyclic heart of the concept lifecycle.

Each revision request consumes a round. The number of rounds a concept may absorb is its **effective revision limit**: its own `revision_limit` plus the sum of the `extra_revisions` granted by every approved change order whose `reason` is `EXTRA_REVISION` and whose `concept_id` names this concept. A revision request is permitted only while the concept's current `rounds_used` is strictly less than that effective revision limit; the comparison uses the count before this round is added. If the concept has already used as many rounds as its effective limit allows, the request is rejected with `ERR_REVISION_LIMIT_REACHED`. When a revision request is accepted, the concept's `rounds_used` is incremented by one, recording the round just taken.

A `StudioOps` operator advances the project from `CONCEPT` to `DELIVERY`. This advance requires that at least one concept on the project has reached `APPROVED`; if none has, it is rejected with `ERR_NO_APPROVED_CONCEPT`.

### 3.5. Delivery, Acceptance, and Handoff

Project delivery is organized around **Deliverables** — the concrete assets the studio ships. A deliverable is created by a `Designer` or a `StudioOps` operator with an `asset_type` drawn from `LOGO_PRIMARY`, `LOGO_MARK`, `COLOR_TOKENS`, `TYPOGRAPHY`, `BRAND_GUIDE`, or `WEB_KIT`, and an optional `is_required_for_handoff` flag that defaults to true and marks whether the asset must be accepted before the project can hand off. A new deliverable starts in `PENDING`. Deliverables can be listed and fetched per project.

A `Designer` delivers an asset, moving it from `PENDING` to `DELIVERED`; the same deliver action also moves an asset back from `REVISION_REQUESTED` to `DELIVERED` after rework. Delivery is allowed only while the parent project is in `DELIVERY` or `HANDOFF`, otherwise `ERR_PROJECT_WRONG_STAGE`. The `Client` then either accepts the asset, moving it from `DELIVERED` to `ACCEPTED` (a terminal state), or requests a revision, moving it from `DELIVERED` to `REVISION_REQUESTED`; neither client action carries a project-stage precondition.

Handing off is the most heavily gated transition in the project lifecycle. A `StudioOps` operator advances the project from `DELIVERY` to `HANDOFF` only when two conditions both hold. First, every deliverable whose `is_required_for_handoff` is true must be in `ACCEPTED`; if any required deliverable is not yet accepted, the advance is rejected with `ERR_DELIVERABLES_INCOMPLETE`. Second, the deposit must be paid in full: the project's `deposit_collected_cents` must be at least its `final_deposit_cents`; if the collected deposit falls short, the advance is rejected with `ERR_DEPOSIT_UNPAID` (HTTP 402). When the advance into `HANDOFF` succeeds it also runs a forward cascade over the project's licenses: every license currently in `RESERVED` or `CLEARED` transitions to `BILLED`, as described in §3.7.

Finally, a `StudioOps` operator completes the project, advancing it from `HANDOFF` to `COMPLETED`. Completion is refused if any invoice on the project is still in `ISSUED` or `OVERDUE` — the project may not close over open invoices — yielding `ERR_OPEN_INVOICES`. On a successful completion the server runs a closing cascade: every milestone still in `PENDING` whose `amount_cents` is zero transitions to `WAIVED`, clearing out the no-charge line items so the project closes cleanly. `COMPLETED` and `CANCELLED` are the two terminal project states.

### 3.6. Milestone Billing and the Invoice Pipeline

Billing a project runs through **Invoices**, each tied to a single milestone. A `BillingOps` operator issues an invoice by naming the `milestone_id` and a `due_date`. Issuing is permitted only while the parent project is in `DELIVERY` or `HANDOFF`, otherwise `ERR_PROJECT_WRONG_STAGE`, and only for a milestone whose `amount_cents` is greater than zero — a zero-amount milestone cannot be invoiced and the attempt is rejected with `ERR_ZERO_AMOUNT_MILESTONE`. Issuing the invoice moves its milestone from `PENDING` to `INVOICED` and creates the invoice in `ISSUED` with its money fields computed. The invoice records its `project_id` and the `milestone_id` it bills, and can be fetched or listed (filterable by `project_id` or `milestone_id`).

The invoice's money fields are computed at issue time in a fixed order. The `gross_cents` is a snapshot of the milestone's `amount_cents`. The `deposit_credit_cents` is the deposit applied to this invoice, taken as the smaller of two quantities: the gross multiplied by the project's `deposit_pct` and rounded half up to whole cents, and the amount of the project's `deposit_collected_cents` that earlier invoices on the project have not already consumed. Deposit credit is drawn down across a project's invoices in the order they are issued, so each invoice credits only the portion of `deposit_collected_cents` not already consumed by previously-issued invoices on the project that are not `VOID`; a voided invoice releases the deposit credit it held back into the available pool for subsequently-issued invoices. The taxable base is the gross minus the deposit credit. The `tax_cents` is that taxable base multiplied by the studio's `tax_rate`, rounded half up to whole cents — and this tax is computed on the credited taxable base, before any late fee. While the invoice is merely `ISSUED` and not overdue, its `late_fee_cents` is zero, and its `net_due_cents` is the taxable base plus the tax.

An invoice can go past due. A `BillingOps` operator marks an invoice overdue, moving it from `ISSUED` to `OVERDUE`, but only once the logical clock has advanced strictly beyond the invoice's `due_date`; calling mark-overdue before that instant is rejected with `ERR_NOT_YET_DUE`. Marking overdue recomputes the late fee on a tiered schedule applied to the net-before-fee figure (the taxable base plus tax). The number of whole days overdue is the elapsed time from the `due_date` to the current clock, rounded up to a whole number of days. If that count is zero or less the late fee is zero; if it is at most thirty days the late fee is the net-before-fee multiplied by a first-tier rate of one and one-half percent (0.015), rounded half up to whole cents; and if it is more than thirty days the late fee is the net-before-fee multiplied by a second-tier rate of three percent (0.030), rounded half up to whole cents. The boundary is inclusive at thirty: exactly thirty days overdue stays in the first tier, and the second tier engages only past thirty days. After the fee is set, `net_due_cents` is recomputed as the taxable base plus tax plus the late fee.

Payment closes the line. A `BillingOps` operator records payment on an invoice that is in either `ISSUED` or `OVERDUE`, moving it to `PAID`; paying an invoice in any other state is an undefined transition and is rejected with `ERR_INVALID_STATE`. Paying the invoice bubbles up to its milestone, moving that milestone to `PAID`. `PAID` and `VOID` are the terminal invoice states, and `PAID` and `WAIVED` are the terminal milestone states.

### 3.7. Stock and Font Licensing

Creative work often consumes purchased stock imagery or fonts, tracked as **Licenses** and billed through to the client with a markup. A `StudioOps` operator reserves a license by naming the consuming `project_id`, a `kind` of `STOCK` or `FONT`, the studio's pass-through acquisition `cost_cents` (zero or greater), and the usage window's `valid_from` and `valid_until`. The license starts in `RESERVED`, and the system computes its `billable_cents` immediately: the cost multiplied by one plus the studio's `license_markup_pct`, rounded half up to whole cents. This per-line rounding is deliberate — each license's billable amount is rounded on its own, and any project-level license total is formed by summing the already-rounded per-line amounts rather than rounding a raw sum. A project's license total is the sum of `billable_cents` over the project's licenses whose `status` is `RESERVED`, `CLEARED`, or `BILLED`; licenses in `VOIDED` are excluded from that total. The usage window is a closed interval and must not overlap another license window on the same project, per §2.10.

A license moves through a short pipeline. A `StudioOps` operator clears a license, moving it from `RESERVED` to `CLEARED`, which is allowed only while the parent project is not yet terminal — that is, not in `COMPLETED` or `CANCELLED` — otherwise `ERR_PROJECT_WRONG_STAGE`. The transition to `BILLED` is not a manual action: when a project advances from `DELIVERY` into `HANDOFF`, the system bills the project's licenses as a cascade, moving every license then in `RESERVED` or in `CLEARED` to `BILLED`. Licenses can be fetched and listed (filterable by `project_id`). The cancellation cascade voids licenses, as covered in §3.9.

### 3.8. Change Orders and the Living Contract Value

Scope rarely holds still, so an activated project's contract value is a living figure adjusted through **Change Orders**. A `StudioOps` operator proposes a change order naming the target `project_id`, a `reason` of `SCOPE_ADD`, `EXTRA_REVISION`, or `RUSH`, a `delta_cents` contract-value adjustment that may be positive or negative, and the `expected_project_version` required by the concurrency rule in §2.7. When the reason is `EXTRA_REVISION`, the proposal also names the `concept_id` being granted more rounds and the number of `extra_revisions` to grant; for any other reason `concept_id` defaults to null and `extra_revisions` defaults to zero. A new change order starts in `PROPOSED`. Change orders can be fetched and listed (filterable by `project_id` or `concept_id`).

Approving a change order is a `Client` action that rewrites the project's ledger. Approval moves the change order from `PROPOSED` to `APPROVED`, but only when the parent project is neither terminal nor already handed off — that is, not in `COMPLETED`, `CANCELLED`, or `HANDOFF`, otherwise `ERR_PROJECT_WRONG_STAGE` — and only when the project has actually been activated, since a project still in `DRAFT` has no ledger to amend, otherwise `ERR_PROJECT_NOT_ACTIVATED`. On approval the server recomputes the project's `contract_value_cents` as `base_scope_cents` plus the sum of the `delta_cents` of every approved change order on the project including the one just approved, then recomputes `final_deposit_cents` as that new contract value multiplied by the project's `deposit_pct`, rounded half up to whole cents. The project's `version` is incremented by one as part of this approval, which is exactly what later renders any in-flight change-order proposal holding an older `expected_project_version` stale. A change order may instead be rejected by the `Client`, moving it from `PROPOSED` to `REJECTED`; rejection carries no precondition and does not touch the ledger. `APPROVED` and `REJECTED` are the terminal change-order states.

### 3.9. Project Cancellation Cascades

Cancelling a live project is an unwind that must leave no child dangling, and the exact set of children touched depends on the stage at which cancellation happens. Cancellation from `DRAFT` touches nothing — the project simply becomes `CANCELLED`.

Cancellation from `DISCOVERY` rejects and voids across the project's children: every moodboard that is not in one of its non-rejectable resting states — that is, every moodboard not currently in `DRAFT` or `SUBMITTED` — transitions to `REJECTED` (a moodboard already in `REJECTED` is left untouched, with no further mutation or `version` bump, so in practice only `APPROVED` moodboards are flipped); every concept that is neither `APPROVED` nor `REJECTED` transitions to `REJECTED`; every change order still in `PROPOSED` transitions to `REJECTED`; every invoice in `ISSUED` or `OVERDUE` transitions to `VOID`; and every license in `RESERVED` or `CLEARED` transitions to `VOIDED`. Whenever an invoice is voided in this cascade, its parent milestone, if it was sitting in `INVOICED`, reverts to `PENDING` so the milestone is freed.

Cancellation from `CONCEPT` runs the parallel unwind for that stage: every concept that is neither `APPROVED` nor `REJECTED` transitions to `REJECTED`; every change order still in `PROPOSED` transitions to `REJECTED`; every invoice in `ISSUED` or `OVERDUE` transitions to `VOID`, again reverting any `INVOICED` parent milestone back to `PENDING`; and every license in `RESERVED` or `CLEARED` transitions to `VOIDED`. Each entity the cascade touches is mutated independently, refreshing its `updated_at` and incrementing its `version`, per §2.8.

### 3.10. Care-Plan Retainers and Billing Cycles

Beyond project work, the studio sells ongoing care plans as **Retainers** against a client. A `StudioOps` operator creates a retainer naming the `client_id`, a fixed `monthly_fee_cents` (zero or greater), the `included_hours` of care bundled into each cycle before overage applies (defaulting to ten), and two overage rates: `tier1_rate_cents`, the per-hour rate for the first five overage hours, and `tier2_rate_cents`, the per-hour rate beyond those first five overage hours. A new retainer starts in `ACTIVE`. Retainers can be fetched and listed (filterable by `client_id`).

A retainer's life is cyclic through pause and resume. A `StudioOps` operator pauses an active retainer, moving it from `ACTIVE` to `PAUSED`, and resumes it, moving it from `PAUSED` back to `ACTIVE`. A retainer can be cancelled from either `ACTIVE` or `PAUSED`, moving it to the terminal `CANCELLED` state. Both pausing and cancelling are blocked while any care cycle on the retainer is still `OPEN`: such an attempt is rejected with `ERR_OPEN_CYCLE`. (Resume carries no such precondition.)

Care is metered in **Care Cycles** under a retainer. A `StudioOps` operator opens a cycle by supplying its `period_start` and `period_end` and an optional `hours_used` count of care hours logged in the cycle (defaulting to zero); the system records the parent `retainer_id` from the path. The window is half-open from `period_start` inclusive to `period_end` exclusive and must not overlap another cycle on the same retainer, per §2.10. The cycle begins in `OPEN`, with its computed `overage_cents` and `billed_cents` at zero until it is closed. Care cycles can be fetched and listed per retainer.

Closing a cycle prices it. A `StudioOps` operator closes a cycle, moving it from `OPEN` to `CLOSED`, but only once the logical clock has reached or passed the cycle's `period_end`; closing earlier is rejected with `ERR_CYCLE_NOT_ENDED`. On close the server computes the overage. The raw overage hours are the cycle's `hours_used` minus the retainer's `included_hours`, floored at zero so there is never negative overage. The first five of those overage hours are billed at the retainer's `tier1_rate_cents`; specifically the first-tier hours are the smaller of the raw overage hours and five. Any overage hours beyond the first five — the raw overage hours minus five, floored at zero — are billed at the retainer's `tier2_rate_cents`. The `overage_cents` is the first-tier hours times the first-tier rate plus the second-tier hours times the second-tier rate; all figures are whole cents per whole hour, so no rounding is needed. The boundary is exact: when overage is at or below five hours the whole of it stays in the first tier, and the second tier engages only beyond five overage hours. When usage is within the included hours the overage is zero. The `billed_cents` is then the retainer's `monthly_fee_cents` plus the computed `overage_cents`. Finally a `BillingOps` operator bills a closed cycle, moving it from `CLOSED` to `BILLED`, the terminal cycle state.

## 4. Endpoint Definitions

Operations that create a new, standalone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including all state-transition actions and the logical-clock and deposit-recording actions — return `200 OK`, except for recording a deposit, which creates a deposit record against the ledger and returns `201 Created`. List and fetch operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | BillingOps, StudioOps |
| POST | `/studios` | Create a studio (tenant root) | StudioOps |
| GET | `/studios/{studioId}` | Get a studio | StudioOps, BillingOps, Designer, Client |
| POST | `/studios/{studioId}/clients` | Register a client under a studio | StudioOps |
| GET | `/studios/{studioId}/clients/{clientId}` | Get a client | StudioOps, BillingOps, Client |
| GET | `/studios/{studioId}/clients` | List clients of a studio | StudioOps, BillingOps |
| POST | `/studios/{studioId}/clients/{clientId}/archive` | Archive a client | StudioOps |
| POST | `/studios/{studioId}/projects` | Create a project in DRAFT | StudioOps |
| GET | `/studios/{studioId}/projects/{projectId}` | Get a project | StudioOps, BillingOps, Designer, Client |
| GET | `/studios/{studioId}/projects` | List projects of a studio | StudioOps, BillingOps, Client |
| POST | `/studios/{studioId}/projects/{projectId}/deposits` | Record a deposit cash payment | BillingOps |
| POST | `/studios/{studioId}/projects/{projectId}/activate` | Activate project DRAFT→DISCOVERY | StudioOps |
| POST | `/studios/{studioId}/projects/{projectId}/advance` | Advance project to next stage | StudioOps |
| POST | `/studios/{studioId}/projects/{projectId}/complete` | Complete project HANDOFF→COMPLETED | StudioOps |
| POST | `/studios/{studioId}/projects/{projectId}/cancel` | Cancel project; cascade children | StudioOps |
| POST | `/studios/{studioId}/projects/{projectId}/moodboards` | Create a moodboard | Designer |
| GET | `/studios/{studioId}/projects/{projectId}/moodboards` | List moodboards of a project | StudioOps, Designer, Client |
| GET | `/studios/{studioId}/projects/{projectId}/moodboards/{moodboardId}` | Get a moodboard | StudioOps, Designer, Client |
| POST | `/studios/{studioId}/projects/{projectId}/moodboards/{moodboardId}/submit` | Submit moodboard for review | Designer |
| POST | `/studios/{studioId}/projects/{projectId}/moodboards/{moodboardId}/approve` | Approve moodboard | Client |
| POST | `/studios/{studioId}/projects/{projectId}/moodboards/{moodboardId}/reject` | Reject moodboard | Client |
| POST | `/studios/{studioId}/projects/{projectId}/concepts` | Create a concept route | Designer |
| GET | `/studios/{studioId}/projects/{projectId}/concepts` | List concepts of a project | StudioOps, Designer, Client |
| GET | `/studios/{studioId}/projects/{projectId}/concepts/{conceptId}` | Get a concept | StudioOps, Designer, Client |
| POST | `/studios/{studioId}/projects/{projectId}/concepts/{conceptId}/present` | Present a concept | Designer |
| POST | `/studios/{studioId}/projects/{projectId}/concepts/{conceptId}/request-revision` | Request a revision round | Client |
| POST | `/studios/{studioId}/projects/{projectId}/concepts/{conceptId}/approve` | Approve a concept | Client |
| POST | `/studios/{studioId}/projects/{projectId}/concepts/{conceptId}/reject` | Reject a concept | Client |
| POST | `/studios/{studioId}/projects/{projectId}/milestones` | Create a milestone (DRAFT only) | StudioOps |
| GET | `/studios/{studioId}/projects/{projectId}/milestones` | List milestones of a project | StudioOps, BillingOps, Client |
| GET | `/studios/{studioId}/projects/{projectId}/milestones/{milestoneId}` | Get a milestone | StudioOps, BillingOps, Client |
| POST | `/studios/{studioId}/invoices` | Issue an invoice for a milestone | BillingOps |
| GET | `/studios/{studioId}/invoices/{invoiceId}` | Get an invoice | StudioOps, BillingOps, Client |
| GET | `/studios/{studioId}/invoices` | List invoices | StudioOps, BillingOps, Client |
| POST | `/studios/{studioId}/invoices/{invoiceId}/mark-overdue` | Mark an invoice overdue | BillingOps |
| POST | `/studios/{studioId}/invoices/{invoiceId}/pay` | Record payment on an invoice | BillingOps |
| POST | `/studios/{studioId}/projects/{projectId}/deliverables` | Create a deliverable | Designer, StudioOps |
| GET | `/studios/{studioId}/projects/{projectId}/deliverables` | List deliverables of a project | StudioOps, Designer, Client |
| GET | `/studios/{studioId}/projects/{projectId}/deliverables/{deliverableId}` | Get a deliverable | StudioOps, Designer, Client |
| POST | `/studios/{studioId}/projects/{projectId}/deliverables/{deliverableId}/deliver` | Deliver an asset | Designer |
| POST | `/studios/{studioId}/projects/{projectId}/deliverables/{deliverableId}/accept` | Accept an asset | Client |
| POST | `/studios/{studioId}/projects/{projectId}/deliverables/{deliverableId}/request-revision` | Request an asset revision | Client |
| POST | `/studios/{studioId}/licenses` | Reserve a stock/font license | StudioOps |
| GET | `/studios/{studioId}/licenses/{licenseId}` | Get a license | StudioOps, BillingOps |
| GET | `/studios/{studioId}/licenses` | List licenses | StudioOps, BillingOps |
| POST | `/studios/{studioId}/licenses/{licenseId}/clear` | Clear a license RESERVED→CLEARED | StudioOps |
| POST | `/studios/{studioId}/change-orders` | Propose a change order (OCC-guarded) | StudioOps |
| GET | `/studios/{studioId}/change-orders/{changeOrderId}` | Get a change order | StudioOps, BillingOps, Client |
| GET | `/studios/{studioId}/change-orders` | List change orders | StudioOps, BillingOps, Client |
| POST | `/studios/{studioId}/change-orders/{changeOrderId}/approve` | Approve a change order | Client |
| POST | `/studios/{studioId}/change-orders/{changeOrderId}/reject` | Reject a change order | Client |
| POST | `/studios/{studioId}/retainers` | Create a care-plan retainer | StudioOps |
| GET | `/studios/{studioId}/retainers/{retainerId}` | Get a retainer | StudioOps, BillingOps, Client |
| GET | `/studios/{studioId}/retainers` | List retainers | StudioOps, BillingOps, Client |
| POST | `/studios/{studioId}/retainers/{retainerId}/pause` | Pause a retainer | StudioOps |
| POST | `/studios/{studioId}/retainers/{retainerId}/resume` | Resume a retainer | StudioOps |
| POST | `/studios/{studioId}/retainers/{retainerId}/cancel` | Cancel a retainer | StudioOps |
| POST | `/studios/{studioId}/retainers/{retainerId}/care-cycles` | Open a billing care cycle | StudioOps |
| GET | `/studios/{studioId}/retainers/{retainerId}/care-cycles` | List care cycles of a retainer | StudioOps, BillingOps |
| GET | `/studios/{studioId}/retainers/{retainerId}/care-cycles/{careCycleId}` | Get a care cycle | StudioOps, BillingOps |
| POST | `/studios/{studioId}/retainers/{retainerId}/care-cycles/{careCycleId}/close` | Close a care cycle | StudioOps |
| POST | `/studios/{studioId}/retainers/{retainerId}/care-cycles/{careCycleId}/bill` | Bill a closed care cycle | BillingOps |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_PROJECT_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PROJECT_WRONG_STAGE` | 409 Conflict |
| `ERR_PROJECT_NOT_ACTIVATED` | 409 Conflict |
| `ERR_NO_MILESTONES` | 409 Conflict |
| `ERR_CLIENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_MOODBOARD_NOT_APPROVED` | 409 Conflict |
| `ERR_NO_APPROVED_CONCEPT` | 409 Conflict |
| `ERR_DELIVERABLES_INCOMPLETE` | 409 Conflict |
| `ERR_DEPOSIT_UNPAID` | 402 Payment Required |
| `ERR_OPEN_INVOICES` | 409 Conflict |
| `ERR_REVISION_LIMIT_REACHED` | 409 Conflict |
| `ERR_INTERVAL_OVERLAP` | 409 Conflict |
| `ERR_ZERO_AMOUNT_MILESTONE` | 409 Conflict |
| `ERR_NOT_YET_DUE` | 409 Conflict |
| `ERR_CYCLE_NOT_ENDED` | 409 Conflict |
| `ERR_OPEN_CYCLE` | 409 Conflict |
| `ERR_INVALID_INTERVAL` | 400 Bad Request |
</content>
</invoke>

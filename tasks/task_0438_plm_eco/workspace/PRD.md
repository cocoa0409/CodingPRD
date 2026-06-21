# Plm Eco API — Product Requirements Document

## 1. Introduction

Hardware engineering organizations live and die by the discipline of their change process. A single component substitution can ripple through dozens of assemblies, invalidate released documentation, and strand units already on the production floor. This document specifies the Product Lifecycle Management (PLM) API, a system that governs the controlled evolution of parts, multi-level bills of material, and the engineering changes that move a design from a working sketch to a released, buildable configuration.

The platform is organized as a graph of peer resources rather than a single nested hierarchy. Parts reference one another through bill-of-material edges to form a multi-level assembly structure; engineering change requests beget change orders; change orders pin part revisions for release; deviations waive nonconforming serialized units; and supplier change notices feed back into the change pipeline. Around this graph the system enforces a strict separation of duties — the person who authors a change cannot rubber-stamp it — together with optimistic concurrency on the most contested resources and a logical clock that gates the moment a change becomes effective.

The sections below define the system-wide contracts first (authentication, response shape, pagination, concurrency, precision, and cascade semantics), then narrate the business workflows that an engineering team performs day to day, and finally summarize the endpoint surface and the error catalogue. The business-logic narrative in Section 3 is the authoritative source for the precise behavior of each operation; the endpoint table in Section 4 is intentionally terse and should be read together with that narrative.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. Every collection is mounted as a peer under the `/plm` namespace; there is no single root resource.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they are acting. If either header is missing or malformed, the request is rejected with `ERR_MISSING_AUTH_HEADER`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The system recognizes six roles, spelled exactly as follows: `Designer`, `ChangeAdmin`, `Approver`, `QualityEngineer`, `SupplierManager`, and `Viewer`. A `Designer` authors parts, revisions, BOM lines, documents, engineering change requests, and deviations, and drives the working-and-review design states. A `ChangeAdmin` owns the approval of change requests and the entire change-order lifecycle, and also releases and obsoletes documents. An `Approver` records decisions on the approval tasks assigned to them. A `QualityEngineer` grants, denies, and expires deviations and manages the build, ship, and conformance state of serialized units. A `SupplierManager` maintains suppliers and the supplier-change-notice lifecycle. A `Viewer` has read-only access to every retrieval endpoint. All six roles may call any GET endpoint.

For every role, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server never compares it to an entity's `id`. It does, however, record it on certain entities where a workflow transition writes it: when a `Designer` submits a change request, their `X-User-ID` is stored as `submitted_by_user_id`; when a `ChangeAdmin` creates a change order, their `X-User-ID` is stored as `created_by_user_id`; and when an `Approver` decides an approval task, their `X-User-ID` is stored as `decided_by_user_id`. These recorded identifiers are later compared against the acting `X-User-ID` only for the segregation-of-duties and task-assignment checks described in Section 3 — they are operator identities, never entity primary keys.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A request whose `limit` is below 1 or above 100, or whose `offset` is negative, is rejected with `ERR_VALIDATION`.

Unless a specific endpoint states otherwise, every list endpoint returns resources sorted by their creation timestamp in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every resource in the system carries a server-minted `id` formatted as a UUID with no type prefix, together with a `created_at` timestamp expressed in ISO 8601 UTC with three fractional digits. Every entity in this domain also carries an `updated_at` timestamp, refreshed on each mutation, and an integer `version` that begins at its initial value when the resource is created and increments by one on every mutation. There are no immutable entities in this domain; all of them expose `updated_at` and `version`.

The system maintains a single logical clock used for every time-based decision — effectivity gating, deviation-window comparisons, and expiry. On server startup the clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly moved it stays at that default rather than tracking real wall-clock time. A `ChangeAdmin` or a `QualityEngineer` may advance the clock by supplying a new instant as `to_iso8601`; this only repositions the clock and never auto-fires any effectivity or expiry transition, which remain explicit operations.

### 2.5. Cascades, Hierarchical Consistency, and Compensating Reverts

Many operations in this system are not isolated — a single action can mutate a chain of related entities. Whenever the system mutates a resource as part of such a cascade, it refreshes that resource's `updated_at` and increments its `version`, exactly as it would for a direct client mutation. The most consequential chain begins when a change order is made effective: each affected part revision is released, any prior released revision of the same part is obsoleted, and serialized units pinned to the obsoleted revision may become nonconforming. The precise hop-by-hop behavior of every cascade is specified in Section 3 alongside the workflow that triggers it.

Several transitions are deliberately reversible to keep the design loops honest. A revision under review can return to working; a rejected change request can be reopened; an in-approval change order can be recalled to draft; and a granted deviation can expire, reverting the units it had waived. Each revert is paired with a compensating action — recall resets the approval tallies, cancel detaches affected items, expiry reverts waived units — so that invariants such as the count of released revisions or the count of conforming units are conserved across the forward-and-back pair.

### 2.6. Nested Resource Retrieval and Left-to-Right Validation

The graph is almost entirely flat under `/plm`, but a handful of reads and writes address a child through its parent — a part's revisions, a revision's bill-of-material lines, and a change order's approval tasks and affected items. For any request that names more than one resource identifier, whether in the path or in the body, the system validates those identifiers left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. Existence checking always precedes state and business-rule evaluation.

### 2.7. Optimistic Concurrency on Contested Parents

Two creation operations branch new children off a parent whose identity legitimately advances with each child, and these are protected by optimistic concurrency control rather than by a state precondition. The first is the creation of a new part revision under a part: the request must carry `expected_part_version`, and it must equal the part's current `version`. Because every new revision bumps the part's `version`, a second create issued against a part view whose `version` has already been advanced by an earlier revision create represents a genuine conflict — the client is acting on a stale view of the part — and the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The second is the addition of a bill-of-material line to a working revision: the request must carry `expected_part_revision_version`, and it must equal that revision's current `version`. Since each added line bumps the revision's `version`, a line add carrying a `version` that has already been superseded by a prior add is likewise rejected with `ERR_STALE_VERSION` (HTTP 412).

Both `expected_part_version` and `expected_part_revision_version` are required, non-optional inputs on their respective create operations. No other endpoint accepts a version field, and no other endpoint performs a version check.

### 2.8. Cost Precision and Rounding

All monetary amounts in this system are integer counts of cents; there are no fractional-cent values stored or returned. The one place rounding arises is in the rolled-up cost of a bill of material, where a per-line extended cost can be fractional before it is reduced to whole cents. The rounding method is round half up, and the order of operations is fixed: the extended cost of each individual line is rounded to whole cents first, and only the already-rounded per-line amounts are summed. The system must never sum the raw fractional line amounts and round the total at the end; the per-line rounding boundary is observable and is part of the contract. The where-used impact analysis produces integer counts of distinct parent parts and involves no rounding.

## 3. Business Logic & Workflows

### 3.1. Suppliers and the Part Catalogue

A `SupplierManager` registers a supplier by supplying its legal `name` and a `supplier_code`. The code is uppercased and must be unique across all suppliers; a duplicate is rejected with `ERR_INVALID_REQUEST`. A new supplier begins life with `status` set to `ACTIVE`, the only alternative being `DISABLED`.

A `Designer` creates a part by supplying a `part_number` (uppercased, unique across all parts — a collision yields `ERR_INVALID_REQUEST`), a descriptive `name`, and a `part_type` of `MAKE`, `BUY`, or `PHANTOM`. The optional `base_cost_cents` defaults to 0 and carries a type-dependent meaning explained in the costing narrative below; it must be zero or greater. Supplier linkage is type-sensitive: a `BUY` part requires a `default_supplier_id` referencing an existing supplier, while a `MAKE` or `PHANTOM` part must omit it (leave it null). Supplying a supplier for a non-`BUY` part, or omitting it for a `BUY` part, is rejected with `ERR_INVALID_REQUEST`. On creation the part's `revision_count` is 0 and its `released_revision_id` is null. The latter is a computed pointer to the single revision of this part currently in the `RELEASED` state, recomputed every time a revision of the part is released or obsoleted; the former is a computed count of the part's revisions. Parts may be filtered in their listing by `part_type`, by `default_supplier_id`, and by `released_revision_id`.

### 3.2. Part Revisions and the Multi-Level Bill of Material

Design content lives on a **part revision**, never on the part itself. A `Designer` branches a new revision off a part; this is the optimistic-concurrency-protected create described in Section 2.7, requiring `expected_part_version`. The system assigns the next `rev_label` in the per-part sequence — the first revision is `A`, then `B`, `C`, and so on — and the revision's `part_id` is set from the parent part. A new revision records the prior released revision it branched from in `supersedes_revision_id` (null for the very first revision). The create increments both the part's `revision_count` and its `version`, and the revision begins in `lifecycle_state` `WORKING`. A revision's `governing_change_order_id` is null until it is attached to a change order. Revisions of a part can be listed and filtered by `lifecycle_state`; the full revision collection can additionally be filtered by `part_id`, by `supersedes_revision_id`, and by `governing_change_order_id`.

A revision's `lifecycle_state` moves through `WORKING`, `IN_REVIEW`, `RELEASED`, and finally the terminal `OBSOLETE`. A `Designer` advances a revision from `WORKING` to `IN_REVIEW`; before this is permitted, a revision whose part is of type `MAKE` or `PHANTOM` must have at least one bill-of-material line, otherwise the submission is rejected with `ERR_EMPTY_BOM`. (A `BUY` revision has no such requirement.) Submitting for review also recomputes the revision's two cost figures. From `IN_REVIEW` a `Designer` may send the revision back to `WORKING`; this return-to-work leg is what makes the revision lifecycle non-linear and carries no preconditions or side effects. A revision reaches `RELEASED` only as a system cascade driven by a change order becoming effective (detailed in Section 3.5), never by a direct client call, and from `RELEASED` it is driven to `OBSOLETE` only as a system cascade when a newer revision of the same part is released.

The bill of material is built from **BOM lines**, each an edge from a parent assembly revision to a child component part. A `Designer` adds a line to a `WORKING` revision; the line records its `parent_revision_id` (the consuming assembly revision), its `child_part_id` (the consumed component, supplied in the request), a `quantity` of at least 1, an optional `scrap_factor` defaulting to 0 that expresses fractional yield loss (for example, 0.005 for half a percent and must be zero or greater), and an optional `reference_designator` placement note defaulting to the empty string. A `quantity` below 1 is rejected with `ERR_INVALID_REQUEST`. Adding a line is the second optimistic-concurrency create from Section 2.7, requiring `expected_part_revision_version`; a successful add increments the revision's `version`. Before the edge is accepted, the system checks that it would not introduce a cycle into the assembly graph — that is, the child part must not, through any chain of its own revisions' lines, transitively consume the parent revision's part. An edge that would close a cycle is rejected with `ERR_BOM_CYCLE`. BOM lines can be listed for a given revision, and the full BOM-line collection can be filtered by `child_part_id` (this is precisely the where-used edge query) and by `parent_revision_id`.

### 3.3. Costing a Bill of Material

Every part revision carries two computed cost figures in integer cents: `planned_cost_cents`, the as-designed rolled-up cost, and `effective_cost_cents`, the as-released rolled-up cost. Both are recomputed when a revision is submitted for review, whenever its cost is queried, whenever a BOM line is added, and whenever a descendant part's revision is released or obsoleted. A dedicated read returns both figures together, echoing the `part_revision_id` alongside `planned_cost_cents` and `effective_cost_cents`.

The roll-up is a bottom-up traversal of the bill of material, evaluating children before parents. For a revision whose part is of type `BUY`, the cost is simply that part's `base_cost_cents` — a `BUY` part is a purchased leaf. For a `MAKE` or `PHANTOM` revision, the system walks the revision's BOM lines in ascending `created_at` order and, for each line, determines the child component's unit cost and then this line's extended cost. The extended cost of a line is its `quantity` multiplied by the child's unit cost multiplied by one plus its `scrap_factor`. That extended cost is rounded half up to whole cents per line, and the rounded per-line amounts are then summed (never summed raw and rounded once, as stressed in Section 2.8). For a `PHANTOM` revision the sum of the lines is the total — a phantom contributes no cost of its own, and its `base_cost_cents` is treated as zero. For a `MAKE` revision, the part's own `base_cost_cents`, representing its labor and overhead adder, is added on top of the summed line costs.

The child's unit cost depends on which of the two figures is being computed, and this is the only difference between them. For `planned_cost_cents`, each child contributes the cost of that child part's latest non-`OBSOLETE` revision, taken by `rev_label` sequence (the newest of `A`, `B`, `C`, and so on) — this reflects the design intent and ignores effectivity. For `effective_cost_cents`, each child contributes the cost of that child part's `released_revision_id` only — the single currently-released revision — and if the child has no released revision, the child contributes its own `base_cost_cents` instead. When a child component has no usable revision under the selected variant, the child contributes its `base_cost_cents`. An empty bill of material is well defined: for a `BUY` or `MAKE` revision the cost is its `base_cost_cents`, and for a `PHANTOM` revision the cost is zero.

### 3.4. Where-Used Impact Analysis

Before a part changes, an engineer needs to know what it would affect. The where-used analysis for a target part reverse-traverses the BOM edges that consume it and reports how many distinct parent parts are impacted, under two interpretations. The response echoes the queried `part_id`, reports `as_designed_affected_count` and `as_released_affected_count`, and lists the `direct_parent_revision_ids` — the parent revision ids that directly consume the target.

The system begins from every BOM line whose child is the target part, finds each such line's parent revision and that revision's owning parent part, and applies two membership rules. A parent part counts toward the as-designed radius when any of its revisions consuming the target is in a state other than `OBSOLETE`; this is the broad blast radius reflecting the design as drawn. A parent part counts toward the as-released radius only when the consuming parent revision is exactly that parent part's `released_revision_id`; this is the narrow blast radius reflecting what is currently shipping. Both counts are integer counts of distinct parent part ids. The walk is transitive and multi-level: the reverse traversal repeats up the assembly tree across non-`OBSOLETE` parent revisions until no new parent part is discovered, so a deeply nested component reports every ancestor assembly that ultimately contains it.

### 3.5. The Engineering Change Pipeline: Request, Order, Approval, Effectivity

Change begins with an **engineering change request (ECR)**. A `Designer` creates one in `DRAFT` status with a `title`, an `affected_part_id` naming the targeted part, and a `reason_code` of `DESIGN_DEFECT`, `COST_REDUCTION`, `SUPPLIER_CHANGE`, or `OBSOLESCENCE`. A request also carries a `source_pcn_id`, which is null unless the request was spawned from an accepted supplier change notice (Section 3.8). The request lifecycle runs `DRAFT`, `SUBMITTED`, and then terminally `APPROVED` or `REJECTED`. When a `Designer` submits a request, the system first confirms the `affected_part_id` part exists (otherwise `ERR_NOT_FOUND`) and stamps `submitted_by_user_id` with the submitter's `X-User-ID`, moving it `DRAFT → SUBMITTED`. A `ChangeAdmin` then approves it (`SUBMITTED → APPROVED`) or rejects it (`SUBMITTED → REJECTED`). A rejected request is not dead: a `Designer` may reopen it, which clears `submitted_by_user_id` and returns it `REJECTED → DRAFT`, closing the revision loop. Change requests can be filtered by `affected_part_id`, by `source_pcn_id`, and by `status`.

An **engineering change order (ECO)** implements an approved request. A `ChangeAdmin` creates one against a `change_request_id`, supplying the `effectivity_date` (an ISO 8601 UTC instant at or after which the order may become effective) and an optional `required_approvals` quorum defaulting to 2 and required to be at least 1. The order records the creator's `X-User-ID` as `created_by_user_id`, starts in `DRAFT` with `approval_count` at 0, and runs the lifecycle `DRAFT`, `IN_APPROVAL`, `APPROVED`, and terminally `EFFECTIVE`, `REJECTED`, or `CANCELLED`. Orders can be filtered by `change_request_id` and by `status`.

While the order is in `DRAFT`, the `ChangeAdmin` populates it. They attach **affected items** — each a `ChangeAffectedItem` naming a `part_revision_id` (a `WORKING` or `IN_REVIEW` revision this order will release on effectivity) and carrying the change order's `change_order_id` and a `pinned` flag that starts false. Attaching an item sets that revision's `governing_change_order_id` to this order. A revision may be governed by at most one non-terminal order at a time; attaching a revision whose `governing_change_order_id` already points to a non-terminal order is rejected with `ERR_REVISION_ALREADY_GOVERNED`. The `ChangeAdmin` also adds **approval tasks** — each an `ApprovalTask` carrying the `change_order_id` and an `assignee_user_id` naming the operator expected to decide it, beginning with `decision` `PENDING` and a null `decided_by_user_id`. Affected items can be listed for an order and across all orders filtered by `part_revision_id` and `change_order_id`; approval tasks can be listed for an order.

Submitting the order for approval moves it `DRAFT → IN_APPROVAL`, but only after three checks pass, evaluated in this order: first, the order must have at least one affected item, else `ERR_NO_AFFECTED_ITEMS`; second, it must have at least `required_approvals` distinct approval tasks, else `ERR_INSUFFICIENT_APPROVERS`; and third, the implemented change request identified by `change_request_id` must itself be in `APPROVED` status, else `ERR_ECR_NOT_APPROVED`. An `IN_APPROVAL` order may be recalled by the `ChangeAdmin` back to `DRAFT`; recall resets every approval task's `decision` to `PENDING`, clears each `decided_by_user_id`, and sets `approval_count` back to 0, making the order machine cyclic.

### 3.6. Approval Quorum and Segregation of Duties

An `Approver` records a decision on an approval task assigned to them. Approving moves the task `PENDING → APPROVED`; rejecting moves it `PENDING → REJECTED`. In both cases three preconditions are enforced, evaluated in order: the parent order must be in `IN_APPROVAL` (otherwise `ERR_INVALID_STATE`); the acting `X-User-ID` must equal the task's `assignee_user_id` (otherwise `ERR_NOT_TASK_ASSIGNEE`); and the acting `X-User-ID` must not equal the parent order's `created_by_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`), so the person who created the order can never approve or reject its tasks. The broader access checks still precede these: a missing or malformed header yields `ERR_MISSING_AUTH_HEADER`, a role other than `Approver` yields `ERR_FORBIDDEN_FOR_ROLE`, and an unknown task id yields `ERR_NOT_FOUND`, before any of the three task-level checks run.

Both decisions stamp the task's `decided_by_user_id` with the acting `X-User-ID`. An approval additionally increments the order's `approval_count` by 1, then evaluates the quorum: the order is considered approved once `approval_count` reaches or exceeds `required_approvals` — the boundary is inclusive, meeting the threshold suffices, it need not be exceeded. When that quorum is met the order cascades `IN_APPROVAL → APPROVED`, and as part of that transition every affected item is pinned: each item's `pinned` flag is set true and the child revision ids of its `part_revision_id` are frozen, so the released configuration is locked at the moment of approval and cannot drift afterward. A rejection takes effect immediately and decisively: a single rejected task cascades the order `IN_APPROVAL → REJECTED`.

### 3.7. Making a Change Effective and the Release Cascade

Once an order is `APPROVED`, a `ChangeAdmin` makes it effective, but only when the logical clock has reached or passed the order's `effectivity_date`; an attempt before that instant is rejected with `ERR_NOT_YET_EFFECTIVE`. Making the order effective transitions it `APPROVED → EFFECTIVE` and fires the central release cascade for each affected item's `part_revision_id`.

The cascade proceeds in hops. First, each affected revision transitions `IN_REVIEW → RELEASED`. This release is only legitimate when an affected item links the revision to an order that is becoming effective (otherwise `ERR_NO_GOVERNING_ECO`) and when that governing order is in `APPROVED` status at make-effective time (otherwise `ERR_ECO_NOT_APPROVED`). On release, the part's `released_revision_id` is set to this revision and the part's `revision_count` is recomputed. Second, if a different prior revision of the same part was already `RELEASED`, that prior revision is driven `RELEASED → OBSOLETE`. Third, for each serialized unit pinned to that now-obsoleted revision whose `conformance_status` is `CONFORMING` and that is not covered by a granted deviation, the unit's `conformance_status` becomes `NONCONFORMING`. Every entity touched along these hops has its `updated_at` refreshed and its `version` incremented, per Section 2.5.

An order can be abandoned. A `ChangeAdmin` may cancel a `DRAFT` or an `IN_APPROVAL` order, moving it to the terminal `CANCELLED`. Cancellation detaches every affected item by clearing each linked revision's `governing_change_order_id`, so those revisions are free to be governed by a future order; when cancelling from `IN_APPROVAL`, the detach additionally sets each affected item's `pinned` back to false. This compensating detach conserves the count of released revisions — cancelling an order never leaves a phantom governance link behind.

### 3.8. Supplier Change Notices

A supplier-driven change enters through a **supplier change notice (PCN)**. A `SupplierManager` records one with a `supplier_id` naming the issuing supplier, an `affected_part_id` naming a part the supplier is changing, and the supplier's external `pcn_reference` as free text. The notice begins in `RECEIVED` and runs `RECEIVED`, `UNDER_ASSESSMENT`, and terminally `ACCEPTED` or `REJECTED`. Its `spawned_ecr_id` is null until acceptance. The `SupplierManager` begins assessment (`RECEIVED → UNDER_ASSESSMENT`), then either rejects it (`UNDER_ASSESSMENT → REJECTED`) or accepts it. Acceptance is only permitted when the `affected_part_id` part is of type `BUY`; accepting against a non-`BUY` part is rejected with `ERR_PART_NOT_BUY`.

Acceptance moves the notice `UNDER_ASSESSMENT → ACCEPTED` and fires a two-hop cascade. First, the system creates a new change request in `DRAFT` whose `affected_part_id` matches the notice's affected part, whose `reason_code` is `SUPPLIER_CHANGE`, and whose `source_pcn_id` points back at this notice. Second, the notice's `spawned_ecr_id` is set to the id of that newly created request, closing the loop between the supplier notice and the engineering change pipeline. Notices can be filtered by `supplier_id`, by `affected_part_id`, by `spawned_ecr_id`, and by `status`.

### 3.9. The Document Vault

Engineering documents are managed in a vault with their own release discipline. A `Designer` creates a document with a unique `doc_number` (uppercased; a duplicate yields `ERR_INVALID_REQUEST`), a `title`, a `doc_type` of `CAD`, `DRAWING`, or `SPEC`, and an optional `part_id` linking the document to the part it describes (null for unattached documents). A document's `lifecycle_state` runs `WORKING`, `IN_REVIEW`, `RELEASED`, and terminally `OBSOLETE`. A `Designer` submits a working document for review (`WORKING → IN_REVIEW`) and may return it to `WORKING`. A `ChangeAdmin` releases a reviewed document (`IN_REVIEW → RELEASED`); if the document is attached to a part, that part must itself have a released revision (its `released_revision_id` must not be null), otherwise the release is rejected with `ERR_PART_NOT_RELEASED`. Finally a `ChangeAdmin` obsoletes a released document (`RELEASED → OBSOLETE`). Documents can be filtered by `part_id` and by `lifecycle_state`.

### 3.10. Deviations and Waivers

When nonconforming units must still be used, a waiver is issued as a **deviation**. A `Designer` creates one with a `part_id` naming the covered part, an optional `change_order_id` naming an order whose release the waiver pre-authorizes against, a `defect_code` of `DIMENSIONAL`, `COSMETIC`, `MATERIAL`, or `FUNCTIONAL`, a `max_units` cap of at least 1 on how many serialized units the waiver may cover, and an inclusive window defined by `effective_from` and `effective_to` (both ISO 8601 UTC). The deviation begins in `DRAFT` with `covered_unit_count` at 0, and runs `DRAFT`, `SUBMITTED`, `GRANTED`, and terminally `DENIED` or `EXPIRED`; `covered_unit_count` is the computed count of serialized units currently pointing at this deviation. Deviations can be filtered by `part_id`, by `change_order_id`, and by `status`.

A `Designer` submits a draft deviation for quality review, but only when its `effective_to` is at or after its `effective_from`; an inverted window is rejected with `ERR_INVALID_WINDOW`, and the submission moves it `DRAFT → SUBMITTED`. A `QualityEngineer` then either denies it (`SUBMITTED → DENIED`) or grants it. A grant is blocked if any other granted deviation for the same `part_id` and the same `defect_code` has a window that overlaps this one, treating both endpoints of the `effective_from`-to-`effective_to` window as inclusive; an overlap is rejected with `ERR_DEVIATION_WINDOW_OVERLAP`.

Granting a deviation moves it `SUBMITTED → GRANTED` and waives units. The system selects the candidate units to waive: serialized units whose pinned revision belongs to the deviation's `part_id`, whose `conformance_status` is `NONCONFORMING`, and whose `deviation_id` is still null. Candidates are ordered by their `created_at` ascending (never by id), and the first `max_units` of them are taken; if there are no candidates the selection is empty and `covered_unit_count` remains 0. For each taken unit, the unit's `deviation_id` is set to this deviation, its `conformance_status` becomes `WAIVED`, and the deviation's `covered_unit_count` is incremented accordingly.

A `QualityEngineer` expires a granted deviation, but only when the logical clock has passed strictly beyond its `effective_to`; an attempt at or before that instant is rejected with `ERR_NOT_YET_EXPIRED`. Expiry moves the deviation `GRANTED → EXPIRED` and reverts its coverage: for each serialized unit whose `deviation_id` equals this deviation and whose `conformance_status` is `WAIVED`, the unit's `conformance_status` returns to `NONCONFORMING`, its `deviation_id` is cleared, and the deviation's `covered_unit_count` is decremented. This revert is the compensating counterpart to the grant, conserving the population of conforming units across the grant-and-expire pair.

### 3.11. Serialization and Configuration Control

A serialized unit tracks a single physical article through two independent state dimensions. A `QualityEngineer` creates one with a unique `serial_number` (uppercased; a duplicate yields `ERR_INVALID_REQUEST`) pinned to a `part_revision_id` representing its as-built configuration. A new unit starts with `build_status` `PLANNED` and `conformance_status` `CONFORMING`. The two dimensions evolve independently on the same row, and units can be filtered by `part_revision_id`, by `deviation_id`, by `build_status`, and by `conformance_status`.

The build dimension runs `PLANNED`, `BUILT`, and terminally `SHIPPED`. A `QualityEngineer` marks a planned unit built, but only when the pinned `part_revision_id` revision is in `RELEASED` state; building against a non-released revision is rejected with `ERR_REVISION_NOT_RELEASED`. The unit then advances `PLANNED → BUILT`. Shipping moves a built unit `BUILT → SHIPPED`, but it is gated by the conformance dimension: a unit may ship only when its `conformance_status` is either `CONFORMING` or `WAIVED`; shipping a `NONCONFORMING` unit is rejected with `ERR_UNIT_NONCONFORMING`.

The conformance dimension cycles among `CONFORMING`, `NONCONFORMING`, and `WAIVED`, and is driven both by operator action and by the cascades described elsewhere. A `QualityEngineer` may manually flag a conforming unit, moving it `CONFORMING → NONCONFORMING`; the same `CONFORMING → NONCONFORMING` transition also occurs automatically when the unit's pinned revision is obsoleted by a release cascade (Section 3.7). A unit moves `NONCONFORMING → WAIVED` automatically when a covering deviation is granted (Section 3.10), and the compensating leg moves it `WAIVED → NONCONFORMING` automatically when that covering deviation expires.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`. Operations that modify an existing resource — including every state-transition action and the logical-clock setter — return `200 OK`. All retrieval endpoints return `200 OK`. The table below is a routing summary only; the request bodies, response payloads, and side effects of each operation are specified in Section 3 and must be read there.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/plm/_clock/set_current_utc` | Set the server logical clock | ChangeAdmin, QualityEngineer |
| POST | `/plm/suppliers` | Create a Supplier | SupplierManager |
| GET | `/plm/suppliers/{id}` | Get a Supplier | All roles |
| GET | `/plm/suppliers` | List Suppliers | All roles |
| POST | `/plm/parts` | Create a Part | Designer |
| GET | `/plm/parts/{id}` | Get a Part | All roles |
| GET | `/plm/parts` | List Parts | All roles |
| GET | `/plm/parts/{id}/where-used` | Where-used impact analysis | All roles |
| POST | `/plm/parts/{id}/revisions` | Create a PartRevision branched from the Part | Designer |
| GET | `/plm/parts/{id}/revisions` | List revisions of a Part | All roles |
| GET | `/plm/part-revisions/{id}` | Get a PartRevision | All roles |
| GET | `/plm/part-revisions` | List PartRevisions | All roles |
| GET | `/plm/part-revisions/{id}/cost` | Computed rolled-up cost (planned and effective) | All roles |
| POST | `/plm/part-revisions/{id}/submit-review` | Submit a WORKING revision for review | Designer |
| POST | `/plm/part-revisions/{id}/return-to-work` | Return an IN_REVIEW revision to WORKING | Designer |
| POST | `/plm/part-revisions/{id}/bom-lines` | Add a BOM line to a WORKING revision | Designer |
| GET | `/plm/part-revisions/{id}/bom-lines` | List BOM lines of a revision | All roles |
| GET | `/plm/bom-lines/{id}` | Get a single BOM line | All roles |
| GET | `/plm/bom-lines` | List BOM lines | All roles |
| POST | `/plm/change-requests` | Create an ECR | Designer |
| GET | `/plm/change-requests/{id}` | Get an ECR | All roles |
| GET | `/plm/change-requests` | List ECRs | All roles |
| POST | `/plm/change-requests/{id}/submit` | Submit an ECR for review | Designer |
| POST | `/plm/change-requests/{id}/approve` | Approve a SUBMITTED ECR | ChangeAdmin |
| POST | `/plm/change-requests/{id}/reject` | Reject a SUBMITTED ECR | ChangeAdmin |
| POST | `/plm/change-requests/{id}/reopen` | Reopen a REJECTED ECR to DRAFT | Designer |
| POST | `/plm/change-orders` | Create an ECO implementing an APPROVED ECR | ChangeAdmin |
| GET | `/plm/change-orders/{id}` | Get an ECO | All roles |
| GET | `/plm/change-orders` | List ECOs | All roles |
| POST | `/plm/change-orders/{id}/affected-items` | Attach a PartRevision as an affected item | ChangeAdmin |
| GET | `/plm/change-orders/{id}/affected-items` | List affected items of an ECO | All roles |
| GET | `/plm/affected-items/{id}` | Get a single affected item | All roles |
| GET | `/plm/affected-items` | List affected items | All roles |
| POST | `/plm/change-orders/{id}/approval-tasks` | Add an approval task to a DRAFT ECO | ChangeAdmin |
| GET | `/plm/change-orders/{id}/approval-tasks` | List approval tasks of an ECO | All roles |
| GET | `/plm/approval-tasks/{id}` | Get an approval task | All roles |
| POST | `/plm/change-orders/{id}/submit-for-approval` | Submit a DRAFT ECO for approval | ChangeAdmin |
| POST | `/plm/change-orders/{id}/recall` | Recall an IN_APPROVAL ECO to DRAFT | ChangeAdmin |
| POST | `/plm/approval-tasks/{id}/approve` | Record APPROVED on an assigned task | Approver |
| POST | `/plm/approval-tasks/{id}/reject` | Record REJECTED on an assigned task | Approver |
| POST | `/plm/change-orders/{id}/make-effective` | Make an APPROVED ECO EFFECTIVE | ChangeAdmin |
| POST | `/plm/change-orders/{id}/cancel` | Cancel a DRAFT or IN_APPROVAL ECO | ChangeAdmin |
| POST | `/plm/documents` | Create a Document in the vault | Designer |
| GET | `/plm/documents/{id}` | Get a Document | All roles |
| GET | `/plm/documents` | List Documents | All roles |
| POST | `/plm/documents/{id}/submit-review` | Submit a WORKING document for review | Designer |
| POST | `/plm/documents/{id}/return-to-work` | Return an IN_REVIEW document to WORKING | Designer |
| POST | `/plm/documents/{id}/release` | Release an IN_REVIEW document | ChangeAdmin |
| POST | `/plm/documents/{id}/obsolete` | Obsolete a RELEASED document | ChangeAdmin |
| POST | `/plm/deviations` | Create a Deviation/waiver | Designer |
| GET | `/plm/deviations/{id}` | Get a Deviation | All roles |
| GET | `/plm/deviations` | List Deviations | All roles |
| POST | `/plm/deviations/{id}/submit` | Submit a DRAFT deviation for review | Designer |
| POST | `/plm/deviations/{id}/grant` | Grant a SUBMITTED deviation | QualityEngineer |
| POST | `/plm/deviations/{id}/deny` | Deny a SUBMITTED deviation | QualityEngineer |
| POST | `/plm/deviations/{id}/expire` | Expire a GRANTED deviation | QualityEngineer |
| POST | `/plm/supplier-change-notices` | Record a Supplier Change Notice | SupplierManager |
| GET | `/plm/supplier-change-notices/{id}` | Get a PCN | All roles |
| GET | `/plm/supplier-change-notices` | List PCNs | All roles |
| POST | `/plm/supplier-change-notices/{id}/assess` | Begin assessing a RECEIVED PCN | SupplierManager |
| POST | `/plm/supplier-change-notices/{id}/accept` | Accept a PCN (BUY part only); spawns an ECR | SupplierManager |
| POST | `/plm/supplier-change-notices/{id}/reject` | Reject a PCN | SupplierManager |
| POST | `/plm/serialized-units` | Create a SerializedUnit pinned to a PartRevision | QualityEngineer |
| GET | `/plm/serialized-units/{id}` | Get a SerializedUnit | All roles |
| GET | `/plm/serialized-units` | List SerializedUnits | All roles |
| POST | `/plm/serialized-units/{id}/build` | Mark a PLANNED unit BUILT | QualityEngineer |
| POST | `/plm/serialized-units/{id}/ship` | Ship a BUILT unit | QualityEngineer |
| POST | `/plm/serialized-units/{id}/flag-nonconforming` | Flag a CONFORMING unit NONCONFORMING | QualityEngineer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_HEADER` | 401 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_BOM_CYCLE` | 409 |
| `ERR_EMPTY_BOM` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_TASK_ASSIGNEE` | 403 |
| `ERR_NO_AFFECTED_ITEMS` | 409 |
| `ERR_INSUFFICIENT_APPROVERS` | 409 |
| `ERR_ECR_NOT_APPROVED` | 409 |
| `ERR_ECO_NOT_APPROVED` | 409 |
| `ERR_NO_GOVERNING_ECO` | 409 |
| `ERR_REVISION_ALREADY_GOVERNED` | 409 |
| `ERR_NOT_YET_EFFECTIVE` | 409 |
| `ERR_DEVIATION_WINDOW_OVERLAP` | 409 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_NOT_YET_EXPIRED` | 409 |
| `ERR_PART_NOT_BUY` | 409 |
| `ERR_PART_NOT_RELEASED` | 409 |
| `ERR_REVISION_NOT_RELEASED` | 409 |
| `ERR_UNIT_NONCONFORMING` | 409 |
| `ERR_VALIDATION` | 422 |

# Ediscovery Litigation Hold API — Product Requirements Document

## 1. Introduction

Litigation discovery is a discipline of provable custody. When a dispute arises, an organization must identify the people who hold relevant data, instruct them to preserve it, collect it defensibly, deduplicate and review it for responsiveness and privilege, produce the responsive non-privileged subset under court-mandated Bates numbering, and — only once the matter resolves — release the preservation obligation so the data may finally be purged. Every step generates an audit trail that opposing counsel may scrutinize, so the chain from "person under hold" to "page produced" must be reconstructible without gaps, overlaps, or accidental disclosure of privileged material.

This document specifies the requirements for an eDiscovery & Litigation Hold API that orchestrates that chain end to end. The system is organized around a **Matter** — the case file — which aggregates custodians, a legal-hold notice and its acknowledgements, collection scopes, processing/deduplication jobs, review batches with privilege tagging, Bates production sets, and clawbacks. Two concerns dominate the design. First, **segregation of duties**: the reviewer who privilege-tags a document must never be the producer who releases the Bates set containing it, and the roles that issue holds, acknowledge them, and manage matter lifecycle are kept distinct. Second, **cascading consistency**: releasing a hold must propagate, in a fixed order, through the active hold notice, every collected scope, and every document, marking data purgeable and custodians eligible for retention release — all atomically and in the correct sequence.

The remainder of this document defines global contracts (authentication, response envelope, pagination, concurrency, precision, and cross-cutting consistency rules) in Section 2, the business workflows and their scattered rules in Section 3, the endpoint surface in Section 4, and the complete error catalogue in Section 5.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. If either header is missing, or if `X-User-Role` does not name one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly five roles: `LegalOps`, `ReviewLead`, `Reviewer`, `Producer`, and `Custodian`. When an authenticated user invokes an endpoint their role is not permitted to call, the request is rejected with `ERR_FORBIDDEN_ROLE`.

Four of the five roles are operator roles whose identity is opaque. When `X-User-Role` is `LegalOps`, `ReviewLead`, `Reviewer`, or `Producer`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The server may, however, record it where a workflow demands it — specifically, when a `Reviewer` records a determination, the server writes that operator's `X-User-ID` onto the document review's `reviewer_user_id` field, and this recorded value is later used to enforce segregation of duties at production time.

The `Custodian` role is different: its identity is entity-backed. When `X-User-Role` is `Custodian`, the `X-User-ID` is the `id` of the acting `Custodian` entity; ownership checks on any resource that references a custodian compare that resource's custodian foreign key to `X-User-ID`. A custodian may therefore acknowledge only their own hold notice and read only their own acknowledgements.

Segregation of duties is a first-class access rule rather than a mere role table. A `Producer` who stages or produces a set must not be the same operator who last decided any document in that set; that conflict is rejected with `ERR_SEGREGATION_OF_DUTIES`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many leading items to skip and defaults to 0. A `limit` or `offset` outside its permitted range is rejected with `ERR_VALIDATION_OUT_OF_RANGE`.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order, with ties at the same `created_at` broken by ascending creation (insertion) order.

List responses include the following fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Computed-Field Reconciliation

Nearly every resource in this system is a top-level resource carrying a standard set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — a system-managed integer that begins at its initial value and increments by one on every mutation. It is the basis for optimistic concurrency control described in §2.6.

There is one exception. The `ProductionItem` resource is a lightweight join record and does **not** carry the full common-field set: it has only an `id` and a `created_at`. It has no `updated_at` and no `version` field. All other resources — `Matter`, `Custodian`, `LegalHold`, `HoldAcknowledgement`, `CollectionScope`, `Document`, `ProcessingJob`, `ReviewBatch`, `DocumentReview`, `ProductionSet`, and `Clawback` — carry the full set.

Many fields on these resources are **computed**, not client-supplied. Whenever an event changes the data underlying a computed field, the server recomputes that field as part of the same operation, refreshing `updated_at` and incrementing `version` on the mutated resource. For example, registering a custodian recomputes the parent matter's `custodian_count`; an acknowledgement recomputes `acknowledged_count` and `ack_rate`. Derived fields are never accepted as input and always reflect the current state of their inputs.

### 2.5. Hierarchical Consistency and Cascade Ordering

The system maintains immediate, ordered consistency across the matter hierarchy. The single most consequential cascade is hold release, which fans out in three numbered hops within one atomic operation. Releasing a matter's hold (hop 1) drives the matter's active hold notice to `RELEASED`. That hold release (hop 2) drives every collection scope on the matter that is in `COLLECTED` or `PROCESSED` to `RELEASED`. Each scope release (hop 3) marks every document under that scope that is not already `PURGEABLE` as `PURGEABLE` and sets the owning custodian's `retention_released` flag to true. Each hop refreshes the `updated_at` of the resources it touches, and the matter mutation that initiates the cascade increments the matter's `version`.

Lesser cascades follow the same discipline. When a legal hold transitions from `DRAFT` to `ISSUED`, it bubbles the parent matter's hold axis from `NO_HOLD` to `HOLD_ACTIVE`. When the first processing job on a matter completes, it bubbles the matter's lifecycle axis from `OPEN` to `IN_DISCOVERY`. The server performs these automatic transitions without an explicit client request on the parent, because the parent's state is defined as a function of its children.

### 2.6. Optimistic Concurrency Control

Most write operations in this system do not take a client-supplied version, because their preconditions already serialize the workflow. There is exactly one operation guarded by optimistic concurrency control: filing a clawback.

A request that files a clawback must carry `expected_production_set_version`, and this field is non-optional for that operation. The value must equal the current `version` of the `ProductionSet` that is the parent of the targeted production item. If another writer has advanced that set's version since the client last read it — for instance, because the set was produced, or because an earlier clawback already retired an item in the same set — then the client's view is stale and the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from filing a clawback against a set whose composition it has not actually observed. Both the produce transition and every successful clawback filing increment the parent set's `version`, which is precisely what a stale client will fail against. No other endpoint accepts or requires a version field.

### 2.7. Bates Numbering and Production Cost Precision

Bates numbering is **matter-global and contiguous**. Every matter tracks a running allocation counter, `next_bates_seq`, which starts at 1 when the matter is created. Each time a production set is staged, it draws its block of sequence numbers starting at the matter's current `next_bates_seq`, and the counter advances past the block so that the next set continues exactly where this one ended. There are no gaps and no reuse across sets within a matter. Each allocated number is rendered as a label by concatenating the matter's `bates_prefix` with the sequence number zero-padded to six digits (for example, prefix `ABC` and sequence 1 yields `ABC000001`).

Production cost is computed in integer cents with a **pinned rounding order**: round per document, then sum. For each document in a staged set, multiply its `page_count` by the per-page rate of 7.3 cents and round that product half-up to a whole number of cents; then sum those already-rounded per-document amounts to obtain the set's `produced_page_count`. The alternative of summing the raw page-times-rate products and rounding once at the end is explicitly incorrect — it produces a different total through rounding drift and must not be used. All half-up rounding in this system rounds a value exactly at the .5 boundary upward.

### 2.8. Validation Ordering and Nested Resource Resolution

When more than one validation could apply to a request, checks run in a fixed priority order so that the surfaced error is deterministic. Authentication comes first: the presence and validity of `X-User-Role` and `X-User-ID` (`ERR_UNAUTHENTICATED`) is checked before anything else, then role permission for the endpoint (`ERR_FORBIDDEN_ROLE`), then — for the produce operation only — the segregation-of-duties check (`ERR_SEGREGATION_OF_DUTIES`). Existence of all path and foreign-key-referenced resources (`ERR_NOT_FOUND`) is verified next, evaluated left to right so that the first identifier in the request that names no existing resource is the one reported. Only after a resource is confirmed to exist is its state checked: if the resource is not in a state from which the requested transition is defined, the request is rejected with `ERR_INVALID_STATE`. Business-specific referential, safety, temporal, and field-shape validations follow, in that general order, and are detailed alongside the workflows they guard in Section 3.

## 3. Business Logic & Workflows

### 3.1. Opening a Matter and Registering Custodians

A `LegalOps` operator opens the case file by creating a **Matter** with a `caption` (the case name, a non-empty string of 1 to 200 characters) and a `bates_prefix`. The `bates_prefix` must consist of uppercase letters only and be 1 to 8 characters long; a prefix that violates this shape is rejected with `ERR_INVALID_REQUEST`, and the prefix is immutable once the matter is created. A new matter begins with its lifecycle axis (`lifecycle_status`) at `OPEN` and its hold axis (`hold_status`) at `NO_HOLD`, with `next_bates_seq` initialized to 1. These two status axes evolve independently: `lifecycle_status` ranges over `OPEN`, `IN_DISCOVERY`, `CLOSING`, and `CLOSED`, while `hold_status` ranges over `NO_HOLD`, `HOLD_ACTIVE`, and `HOLD_RELEASED`. Its many computed rollups — `custodian_count`, `acknowledged_count`, `ack_rate`, `responsive_doc_count`, `produced_document_count`, `clawed_back_document_count`, and `spoliation_risk_score` — all start at their zero baselines.

Onto a matter, `LegalOps` registers each **Custodian** — a person whose data may be relevant — supplying the `matter_id` of the parent matter, the custodian's `full_name` (non-empty), and their `email`. Email must be unique within a matter, compared case-insensitively; a second custodian on the same matter with an email that case-insensitively matches an existing one is rejected with `ERR_DUPLICATE_CUSTODIAN_EMAIL`. Each custodian starts with an `ack_state` of `NONE` and a `retention_released` flag of false. Registering a custodian recomputes the matter's `custodian_count`, which counts the custodian rows attached to that matter.

### 3.2. Issuing the Legal Hold and Collecting Acknowledgements

Preservation begins with a **LegalHold** notice. A `LegalOps` operator drafts one against a matter by supplying its `matter_id`, a non-empty `title`, the preservation `instructions` text, and an `ack_deadline` — the ISO 8601 UTC instant by which custodians must acknowledge. A freshly drafted hold has `status` `DRAFT`, a null `issued_at`, and a `pending_ack_count` of 0.

Issuing the hold advances it from `DRAFT` to `ISSUED`. This is permitted only while the hold is in `DRAFT` and only when the matter has at least one custodian registered; an attempt to issue a hold on a matter with zero custodians is rejected with `ERR_HOLD_HAS_NO_CUSTODIANS`. On issue, the server stamps `issued_at` with the current time and fans out preservation obligations: for every custodian on the matter it creates a **HoldAcknowledgement** in `PENDING` status and sets that custodian's `ack_state` to `PENDING`. Issuing also bubbles the matter's hold axis from `NO_HOLD` to `HOLD_ACTIVE` (see §2.5). A hold's `pending_ack_count` reflects how many of its acknowledgements remain `PENDING`.

Each HoldAcknowledgement carries the `hold_id` of its notice and the `custodian_id` of the obligated custodian, begins in `PENDING` with a null `acknowledged_at`, and carries an `on_time` flag that is initially false. A `Custodian` acknowledges their own notice — and only their own — which advances that acknowledgement from `PENDING` to `ACKNOWLEDGED`. This is permitted only while the acknowledgement is `PENDING` and its parent hold is `ISSUED`. On acknowledgement, the server stamps `acknowledged_at` with the current time and sets `on_time` to true exactly when `acknowledged_at` is at or before the hold's `ack_deadline` — the deadline instant itself counts as on time. It sets the custodian's `ack_state` to `ACKNOWLEDGED` and recomputes the matter's `acknowledged_count` (custodians acknowledged against the active hold) and `ack_rate`. It then decrements the hold's `pending_ack_count`; if that count reaches 0, meaning every custodian has acknowledged, the hold auto-transitions from `ISSUED` to `ACKNOWLEDGED`.

The matter's `ack_rate` is the `acknowledged_count` divided by the `custodian_count`, rounded half-up to two decimal places; when the matter has no custodians it is 0.00 rather than an undefined division.

### 3.3. Spoliation Risk Scoring

`LegalOps` may at any time read a matter's **spoliation risk**, a computed read that returns two integers: a provisional risk and a final risk. The score is recomputed whenever a hold is issued and on every acknowledgement, and the final variant is also the value persisted on the matter as `spoliation_risk_score`.

The score is built from three inputs. Let *U* be an unacknowledged-custodian count (defined per variant below), *D* be the number of whole days elapsed since the hold's `issued_at` (or 0 when no hold has been issued), and *R* be the matter's `responsive_doc_count`. The base is fifteen points for each unacknowledged custodian plus two points for each day since issuance, where the day contribution is capped — the day term uses the smaller of *D* and 30, so days beyond the thirtieth add nothing. A tiered multiplier is then applied based on responsive volume: the multiplier is 1.0 when *R* is below 100, 1.2 when *R* is at least 100 but below 1000, and 1.5 when *R* is 1000 or more. The score is the base multiplied by that multiplier, rounded half-up to an integer, and finally capped so it never exceeds 100.

The two variants differ only in how *U* is counted. The **provisional** variant — displayed live during the acknowledgement window — counts every custodian whose `ack_state` is not `ACKNOWLEDGED`, so custodians still `PENDING` count as risk. The **final** variant — the value persisted as `spoliation_risk_score` — counts only custodians who have no HoldAcknowledgement record at all, excusing those who have a `PENDING` record. The risk read returns the provisional figure as the live number and the final figure as the persisted number; concretely, its `data` object carries exactly two integer fields, `provisional_risk` (the provisional figure) and `final_risk` (the final figure).

### 3.4. Defining and Running Collection

A **CollectionScope** describes one slice of data to collect from one custodian. `LegalOps` defines a scope by supplying the `matter_id`, the `custodian_id` whose data it collects, a non-empty `source_label` (for example, a mailbox name), an inclusive `range_start`, an exclusive `range_end`, and an `expected_doc_count` — the custodian's projected volume, which must be at least 0. The collection date window is a half-open interval `[range_start, range_end)`. The `range_start` must be strictly before `range_end`; a start that is not strictly before the end is rejected with `ERR_INVALID_DATE_RANGE`. Furthermore, two scopes for the same custodian on the same matter may not have overlapping windows; because the interval is half-open, one scope's window touching another exactly at the shared boundary instant does not overlap, but any genuine overlap is rejected with `ERR_SCOPE_DATE_OVERLAP`. A new scope starts in `DEFINED` status with a `collected_actual_count` of 0.

Starting collection advances a scope from `DEFINED` to `COLLECTING`. This requires the scope to be in `DEFINED`, the matter's hold axis to be `HOLD_ACTIVE`, and — critically — the scope's custodian to have already reached `ack_state` `ACKNOWLEDGED`; collection that begins before its custodian has acknowledged the hold is rejected with `ERR_CUSTODIAN_NOT_ACKNOWLEDGED`. Finishing collection advances the scope from `COLLECTING` to `COLLECTED`.

While a scope is collecting, `LegalOps` ingests **Document** rows into it. Each document is supplied with the `scope_id` of its collecting scope, a non-empty hexadecimal `content_hash` used for duplicate detection, and a `page_count` of at least 1. On ingest the server denormalizes the `matter_id` from the scope (so matter-level rollups need not traverse the scope), sets the document's `status` to `COLLECTED`, and recomputes the scope's `collected_actual_count` (the count of documents under the scope at `COLLECTED` status or beyond). Every freshly ingested document begins with `privilege_tag` `UNREVIEWED`, `responsiveness_tag` `UNREVIEWED`, and a null `duplicate_of_id`. Documents can later be listed and filtered by `scope_id`, `matter_id`, `status`, or by the original they duplicate via `duplicate_of_id`.

A matter's collection volume is a computed read returning two integers. The forward-looking **estimate** sums the `expected_doc_count` of scopes still in `DEFINED` or `COLLECTING` — that is, the projected volume of data not yet collected. The realized **actual** sums the `collected_actual_count` of scopes in `COLLECTED`, `PROCESSED`, or `RELEASED` — the chronological count of what has actually been collected. The read returns both side by side; concretely, its `data` object carries exactly two integer fields, `estimate_total` (the estimate) and `actual_total` (the actual).

### 3.5. Processing and Deduplication

Once a scope is `COLLECTED`, `LegalOps` queues a **ProcessingJob** against it by supplying the job's `matter_id` and the `scope_id` whose collected documents it will process. A new job begins `QUEUED` with `total_input_count`, `unique_count`, and `duplicate_count` all at 0. Running the job advances it from `QUEUED` to `RUNNING`; this requires the job to be `QUEUED` and its referenced scope to be `COLLECTED`, and on the transition the server snapshots `total_input_count` as the number of `COLLECTED` documents under the scope at that moment. A running job may instead be marked `FAILED`, which simply moves it from `RUNNING` to `FAILED`.

Completing a job advances it from `RUNNING` to `COMPLETED` and runs **deduplication**. The job processes the documents under its scope that are in `COLLECTED` status, walking them in ascending `created_at` order, with ties at the same `created_at` broken by ascending creation (insertion) order. It keeps a memory of which `content_hash` values it has already seen. For each document in order, if its `content_hash` has already been seen, the document is marked `DUPLICATE` and its `duplicate_of_id` is set to the `id` of the first document that exhibited that hash; otherwise it is promoted to `UNIQUE` and its hash is remembered as first-seen. The job records `unique_count` as the number of documents it promoted to `UNIQUE` and `duplicate_count` as the number it marked `DUPLICATE`. The deduplication key is **matter-wide**: a `content_hash` that was already first-seen by an earlier scope's completed job on the same matter makes the new document a `DUPLICATE` across scopes, pointing at that earlier first-seen document. Completing the job also bubbles the scope from `COLLECTED` to `PROCESSED`, and — if this is the first job to complete on the matter — bubbles the matter's lifecycle from `OPEN` to `IN_DISCOVERY`.

### 3.6. Review Batches, Reviewer Decisions, and Tag Freezing

A `ReviewLead` organizes deduplicated documents into a **ReviewBatch**, created with the parent `matter_id` and a non-empty `name`. A new batch is `DRAFT` with a `document_count` and `reviewed_count` of 0. The lead populates the batch by adding documents to it for review; each addition supplies a `document_id` and creates a **DocumentReview** join row. The added document must be a `UNIQUE` (post-dedup) document belonging to the same matter as the batch; an attempt to add a non-unique document, or one from a different matter, is rejected with `ERR_DOCUMENT_NOT_UNIQUE`. Each addition recomputes the batch's `document_count` (the number of review rows on it). A DocumentReview carries the `batch_id` of its batch and the `document_id` it covers, begins with a `decision` of `UNDECIDED` and a null `reviewer_user_id`.

Opening review advances the batch from `DRAFT` to `IN_REVIEW`; this requires the batch to be `DRAFT` and to hold at least one document, and an attempt to open an empty batch is rejected with `ERR_EMPTY_BATCH`. While the batch is in review, a `Reviewer` records a per-document determination, setting the review row's `decision` to one of `RESPONSIVE_NOT_PRIV`, `RESPONSIVE_PRIV`, `RESPONSIVE_REDACTED`, or `NON_RESPONSIVE`. Recording a decision writes the reviewer's `X-User-ID` onto the review's `reviewer_user_id` (so the deciding operator is remembered for segregation-of-duties enforcement later) and recomputes the batch's `reviewed_count`, the number of review rows whose decision is no longer `UNDECIDED`.

Submitting the batch to QC advances it from `IN_REVIEW` to `QC_REVIEW`; this is permitted only when every document has been decided — that is, when `reviewed_count` equals `document_count`. Submitting while some documents remain undecided is rejected with `ERR_BATCH_NOT_FULLY_REVIEWED`. A batch in `QC_REVIEW` may be reopened back to `IN_REVIEW` (the revision loop, during which reviewers may change their decisions) or completed.

Completing the batch advances it from `QC_REVIEW` to `COMPLETED` and **freezes** each document's tags from its review decision according to a fixed mapping: a decision of `RESPONSIVE_NOT_PRIV` sets the document's `responsiveness_tag` to `RESPONSIVE` and its `privilege_tag` to `NOT_PRIVILEGED`; `RESPONSIVE_PRIV` sets `RESPONSIVE` and `PRIVILEGED`; `RESPONSIVE_REDACTED` sets `RESPONSIVE` and `REDACTED`; and `NON_RESPONSIVE` sets `NON_RESPONSIVE` and `NOT_PRIVILEGED`. Completion then recomputes the matter's `responsive_doc_count` as the number of this matter's `UNIQUE` documents whose `responsiveness_tag` is `RESPONSIVE` across all completed batches.

### 3.7. Bates Production, Validation Fork, and Producing

A `Producer` assembles a **ProductionSet** from a completed review batch, supplying the `matter_id` and the `source_batch_id` of the batch it draws from. A new set is `DRAFT` with a null `bates_start`, null `bates_end`, `item_count` of 0, and null `produced_page_count`. The producer adds documents to the set as **ProductionItem** rows, each supplying a `document_id`; a successful add recomputes the set's `item_count`. A document already tagged `PRIVILEGED` may not be added as a production item — that attempt is rejected with `ERR_PRIVILEGED_DOCUMENT`. Each production item carries the `set_id` of its set and the `document_id` it produces, begins in `STAGED` status, and has a null `bates_number` until the set is staged.

Validating the set advances it from `DRAFT` to `VALIDATING`. This requires the set to be `DRAFT`, to hold at least one item (validating an empty set is rejected with `ERR_EMPTY_PRODUCTION_SET`), and its source batch to be `COMPLETED` (validating against a batch that is not yet completed is rejected with `ERR_BATCH_NOT_COMPLETED`). From `VALIDATING` the set **forks** automatically. If validation finds at least one item whose document is tagged `PRIVILEGED`, the set moves to `BLOCKED`. If no item's document is `PRIVILEGED`, the set moves to `STAGED`, and on that clean staging the server allocates Bates numbers and computes cost: it sets `bates_start` to the matter's current `next_bates_seq`, assigns each item a sequential `bates_number` in ascending document-`created_at` order (ties at the same `created_at` broken by ascending document creation/insertion order), sets `bates_end` to the last number used (the start plus `item_count` minus one), advances the matter's `next_bates_seq` to one past `bates_end`, and computes `produced_page_count` via the per-document-then-sum cost rule of §2.7. A `BLOCKED` set can be revised back to `DRAFT`, where the producer removes or redacts the offending privileged items before validating again.

Producing the set advances it from `STAGED` to `PRODUCED`. This requires the set to be `STAGED` and the matter's lifecycle to be in either `IN_DISCOVERY` or `CLOSING`. It is also the point where segregation of duties is enforced: the producing operator's `X-User-ID` must not equal the `reviewer_user_id` recorded on any document review covering a document in this set; if it does, the production is rejected with `ERR_SEGREGATION_OF_DUTIES`. On a successful produce, the set moves to `PRODUCED`, each of its production items moves from `STAGED` to `PRODUCED`, the matter's `produced_document_count` is recomputed, and the set's `version` is incremented.

### 3.8. Clawbacks and Concurrency

After production, privileged material occasionally slips through and must be retracted. A `Producer` files a **Clawback** against a produced item, supplying the `matter_id`, the `production_item_id` being clawed back, a non-empty `reason`, and the `expected_production_set_version` carrying the producer's last observed `version` of the item's parent production set. The version check is the optimistic-concurrency guard of §2.6: if the supplied `expected_production_set_version` does not match the parent set's current `version`, the filing is rejected with `ERR_STALE_VERSION`. A successful filing creates the clawback in `REQUESTED` status and increments the parent production set's `version` by one (which is why a second clawback filed against a stale view of the same set fails the version check).

A requested clawback resolves one of two ways. Sequestering it advances it from `REQUESTED` to `SEQUESTERED`; this requires the referenced production item to be `PRODUCED`, and on sequester the server retires the item by moving it from `PRODUCED` to `CLAWED_BACK`, re-tags the item's document `privilege_tag` to `PRIVILEGED`, and recomputes the matter's `produced_document_count` and `clawed_back_document_count` so that the produced-plus-clawed-back total is conserved. The matter's `produced_document_count` counts production items across the matter's produced sets that are not `CLAWED_BACK`, while its `clawed_back_document_count` counts items across the matter's sets that are `CLAWED_BACK`. Alternatively, a `LegalOps` operator may dispute a requested clawback, advancing it from `REQUESTED` to `DISPUTED`; the production item then stays `PRODUCED`.

### 3.9. Matter Lifecycle Close-Out and Retention Release

The matter's two axes converge at close-out, driven by `LegalOps`. Beginning close advances the lifecycle from `IN_DISCOVERY` to `CLOSING`; this requires the lifecycle to currently be `IN_DISCOVERY` and requires that no production set on the matter is still in `DRAFT` or `VALIDATING`, so that no production work is left mid-flight.

Releasing the hold advances the hold axis from `HOLD_ACTIVE` to `HOLD_RELEASED`. This requires the hold axis to currently be `HOLD_ACTIVE` and the lifecycle to be `CLOSING`. The release triggers the three-hop cascade described in §2.5: the active hold notice (whether `ISSUED` or `ACKNOWLEDGED`) moves to `RELEASED`; every collection scope on the matter in `COLLECTED` or `PROCESSED` moves to `RELEASED`; and every document under each released scope that is not already `PURGEABLE` becomes `PURGEABLE` while its custodian's `retention_released` flag is set to true. Releasing the hold increments the matter's `version`.

Closing the matter advances the lifecycle from `CLOSING` to `CLOSED`, the terminal state. This requires the lifecycle to currently be `CLOSING` and the hold axis to already be `HOLD_RELEASED` — a matter cannot be closed while data is still under preservation. Closing increments the matter's `version`.

For test determinism, an administrative `LegalOps` capability pins the server's notion of the current UTC instant: it accepts a `to_iso8601` value and sets the clock used for all subsequent now-stamping (such as `issued_at` and `acknowledged_at`), returning the new current time in a `data` object whose single field `now` holds that pinned instant as an ISO 8601 UTC timestamp.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new distinct resource to a collection return a `201 Created` status code. State-transition operations and other modifications of an existing resource return a `200 OK` status code. Computed reads and fetches likewise return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/matters` | Create a matter | LegalOps |
| GET | `/matters/{id}` | Fetch a matter | LegalOps, ReviewLead, Reviewer, Producer |
| GET | `/matters` | List matters | LegalOps, ReviewLead, Reviewer, Producer |
| GET | `/matters/{id}/risk` | Computed read: provisional + final spoliation risk | LegalOps |
| GET | `/matters/{id}/collection-summary` | Computed read: estimate vs actual collection volume | LegalOps |
| POST | `/matters/{id}/begin-close` | Advance matter lifecycle to CLOSING | LegalOps |
| POST | `/matters/{id}/release-hold` | Release litigation hold; cascade retention release | LegalOps |
| POST | `/matters/{id}/close` | Advance matter lifecycle to CLOSED | LegalOps |
| POST | `/custodians` | Register a custodian on a matter | LegalOps |
| GET | `/custodians/{id}` | Fetch a custodian | LegalOps, ReviewLead, Producer |
| GET | `/custodians` | List/filter custodians by matter | LegalOps, ReviewLead, Producer |
| POST | `/legal-holds` | Draft a legal-hold notice for a matter | LegalOps |
| GET | `/legal-holds/{id}` | Fetch a legal hold | LegalOps, ReviewLead |
| GET | `/legal-holds` | List/filter legal holds by matter | LegalOps, ReviewLead |
| POST | `/legal-holds/{id}/issue` | Issue the hold; fan out PENDING acknowledgements | LegalOps |
| GET | `/hold-acknowledgements/{id}` | Fetch an acknowledgement | LegalOps, Custodian |
| GET | `/hold-acknowledgements` | List/filter acknowledgements by hold or custodian | LegalOps, Custodian |
| POST | `/hold-acknowledgements/{id}/acknowledge` | Custodian acknowledges the hold notice | Custodian |
| POST | `/collection-scopes` | Define a collection scope for a custodian | LegalOps |
| GET | `/collection-scopes/{id}` | Fetch a collection scope | LegalOps, Producer |
| GET | `/collection-scopes` | List/filter collection scopes by matter or custodian | LegalOps, Producer |
| POST | `/collection-scopes/{id}/start` | Begin collection | LegalOps |
| POST | `/collection-scopes/{id}/finish` | Finish collection | LegalOps |
| POST | `/documents` | Ingest a collected document into a COLLECTING scope | LegalOps |
| GET | `/documents/{id}` | Fetch a document | LegalOps, ReviewLead, Reviewer, Producer |
| GET | `/documents` | List/filter documents by scope, matter, status, or original | LegalOps, ReviewLead, Reviewer, Producer |
| POST | `/processing-jobs` | Queue a processing/dedup job for a COLLECTED scope | LegalOps |
| GET | `/processing-jobs/{id}` | Fetch a processing job | LegalOps |
| GET | `/processing-jobs` | List/filter processing jobs by matter or scope | LegalOps |
| POST | `/processing-jobs/{id}/run` | Start the job (snapshots input set) | LegalOps |
| POST | `/processing-jobs/{id}/complete` | Complete dedup; promote UNIQUE/DUPLICATE; bubble lifecycle | LegalOps |
| POST | `/processing-jobs/{id}/fail` | Mark the job FAILED | LegalOps |
| POST | `/review-batches` | Create a review batch | ReviewLead |
| GET | `/review-batches/{id}` | Fetch a review batch | ReviewLead, Reviewer, Producer |
| GET | `/review-batches` | List/filter review batches by matter | ReviewLead, Reviewer, Producer |
| POST | `/review-batches/{id}/reviews` | Add a UNIQUE document to the batch for review | ReviewLead |
| GET | `/review-batches/{id}/reviews` | List DocumentReview rows on the batch | ReviewLead, Reviewer, Producer |
| POST | `/review-batches/{id}/open-review` | Open the batch for review | ReviewLead |
| POST | `/review-batches/{id}/submit-qc` | Submit the batch to QC | ReviewLead |
| POST | `/review-batches/{id}/reopen` | Reopen the batch from QC to review | ReviewLead |
| POST | `/review-batches/{id}/complete` | Complete the batch; freeze tags | ReviewLead |
| GET | `/document-reviews/{id}` | Fetch a document review | ReviewLead, Reviewer, Producer |
| GET | `/document-reviews` | List/filter document reviews by batch or document | ReviewLead, Reviewer, Producer |
| POST | `/document-reviews/{id}/decide` | Record a privilege/responsiveness decision | Reviewer |
| POST | `/production-sets` | Create a Bates production set from a COMPLETED batch | Producer |
| GET | `/production-sets/{id}` | Fetch a production set | Producer, LegalOps |
| GET | `/production-sets` | List/filter production sets by matter or source batch | Producer, LegalOps |
| POST | `/production-sets/{id}/items` | Add a non-privileged document to the production set | Producer |
| GET | `/production-sets/{id}/items` | List ProductionItems on the set | Producer, LegalOps |
| POST | `/production-sets/{id}/validate` | Validate; fork to BLOCKED or STAGED with Bates allocation | Producer |
| POST | `/production-sets/{id}/revise` | Return a BLOCKED set to DRAFT for rework | Producer |
| POST | `/production-sets/{id}/produce` | Produce a STAGED set (segregation-of-duties enforced) | Producer |
| GET | `/production-items/{id}` | Fetch a production item | Producer, LegalOps |
| GET | `/production-items` | List/filter production items by set or document | Producer, LegalOps |
| POST | `/clawbacks` | File a clawback against a PRODUCED item | Producer |
| GET | `/clawbacks/{id}` | Fetch a clawback | Producer, LegalOps |
| GET | `/clawbacks` | List/filter clawbacks by matter or production item | Producer, LegalOps |
| POST | `/clawbacks/{id}/sequester` | Sequester; retire the item | Producer |
| POST | `/clawbacks/{id}/dispute` | Dispute; item stays PRODUCED | LegalOps |
| POST | `/_clock/set_current_utc` | Test-driving: pin the server's current UTC time | LegalOps |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_BATCH_NOT_COMPLETED` | 409 |
| `ERR_CUSTODIAN_NOT_ACKNOWLEDGED` | 409 |
| `ERR_PRIVILEGED_DOCUMENT` | 422 |
| `ERR_DOCUMENT_NOT_UNIQUE` | 422 |
| `ERR_SCOPE_DATE_OVERLAP` | 409 |
| `ERR_DUPLICATE_CUSTODIAN_EMAIL` | 409 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_HOLD_HAS_NO_CUSTODIANS` | 409 |
| `ERR_VALIDATION_OUT_OF_RANGE` | 422 |
| `ERR_BATCH_NOT_FULLY_REVIEWED` | 409 |
| `ERR_EMPTY_BATCH` | 409 |
| `ERR_EMPTY_PRODUCTION_SET` | 409 |

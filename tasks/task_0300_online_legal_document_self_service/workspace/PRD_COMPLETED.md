# Online Legal Document Self-Service API — Product Requirements Document

## 1. Introduction

The Online Legal Document Self-Service platform lets ordinary consumers produce legally meaningful documents — a will, an LLC formation, a power of attorney, or a residential lease — without retaining a lawyer up front. A customer chooses a document family and a governing US state, works through a guided questionnaire, and the platform assembles the correct state-specific clauses into a finished draft. For matters where extra assurance is warranted, the customer can elect a paid attorney-review add-on; a licensed attorney then examines the assembled draft and either approves it or sends it back for revision. Finished documents flow into an e-signature envelope, optionally with a notary referral, and are kept in secure storage with periodic update reminders.

This API is the backend contract for that experience. It is built around a small number of peer top-level collections — customers, subscription plans, subscriptions, clause templates, document projects, revisions, attorneys, reviews, signature envelopes, notary referrals, orders, and reminders — all mounted under the `/legal` path prefix and linked to one another through foreign-key fields carried in request bodies rather than through deep nested paths. The dominant theme is **workflow orchestration**: a document project moves through a fairly long lifecycle, several actions in that lifecycle cascade into sibling entities, and money is charged and refunded as the project advances and retreats. A second theme is **compliance and auditability**: every monetary movement must reconcile, every credit consumed must be conservable, and revision history must be immutable and ordered. The sections that follow define the global contract first, then the scattered business logic that an implementer must reassemble into a working system.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which that principal acts. The platform recognizes exactly three roles, spelled precisely as `Customer`, `Attorney`, and `PlatformAdmin`. If the `X-User-Role` header is missing or names a value outside this set, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the header is present and valid but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). These two checks run before any other validation; authentication precedes authorization, and authorization precedes everything else.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that ultimately references a `Customer` compare the resource's owning `customer_id` (directly, or through the project it belongs to) against `X-User-ID`. When `X-User-Role` is `Attorney`, `X-User-ID` is the `id` of the acting `Attorney`; an attorney may only advance a review whose `attorney_id` equals `X-User-ID`, and an attempt to advance someone else's review is rejected with `ERR_NOT_REVIEW_OWNER` (HTTP 403). When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server accepts it for the administrative and system operations the admin is empowered to perform but does not compare it to any entity's `id`. The `Customer` and `PlatformAdmin` roles jointly may create customers and subscriptions; the `PlatformAdmin` role alone manages the plan catalog, the clause library, attorney onboarding, subscription lifecycle, the system clock, and reminder dispatch; the `Attorney` and `Customer` roles, alongside the admin, may read most resources.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. A supplied `limit` outside that range is clamped into it (a value below 1 becomes 1, a value above 100 becomes 100) rather than rejected. The `offset` parameter specifies the number of items to skip and defaults to 0; a supplied negative `offset` is clamped to 0. A `limit` or `offset` that is present but not parseable as an integer is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most top-level resources carry a standard set of system-managed fields. Every such resource has an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp, formatted as an ISO 8601 UTC instant with three fractional digits. Mutable resources additionally carry an `updated_at` timestamp, refreshed on every change, and an integer `version` that begins at 1 and increments by one on each mutation, supporting the optimistic-concurrency mechanism described in §2.6.

There is one deliberate exception. The `AssembledClause` resource is immutable once written: it is a frozen snapshot of a clause template taken at assembly time, and it carries only `id` and `created_at`. An `AssembledClause` has no `updated_at` field and no `version` field; it is never individually mutated after creation. Every other resource described in this document — customers, plans, subscriptions, clause templates, projects, questionnaire responses, revisions, attorneys, reviews, signature requests, notary referrals, orders, and update reminders — carries the full `id` / `created_at` / `updated_at` / `version` quartet.

### 2.5. Hierarchical Consistency and Cascading Side Effects

A central design property of this platform is that a single client action frequently mutates more than one resource. When the system performs such a secondary mutation, it is a real mutation in every sense: the affected resource's `updated_at` is refreshed and its `version` is incremented, exactly as if a client had acted on it directly. This is true whether the mutation is a state transition driven into a child entity, a counter adjusted on a parent, or a monetary field recomputed on an order. Implementers must treat server-initiated cascades and client-initiated changes identically with respect to these audit fields.

Several cascades in this system run multiple hops deep — a subscription cancellation locks the customer's projects, each locked project cancels its in-flight reviews, and each cancelled review refunds money on its order. The full chains are spelled out in §3 alongside the workflows that originate them. The governing rule here is simply that every hop is durable and individually recorded, and that the order of hops is deterministic.

### 2.6. Optimistic Concurrency on Revision Creation

Creating a new document revision is the one write in this system guarded by optimistic concurrency control. A revision is a point-in-time snapshot of a project's assembled document, and creating one legitimately supersedes the project's prior snapshot. To prevent a client from snapshotting a project whose state it has not actually observed, the create request must carry `expected_document_project_version`, set to the `version` of the target `DocumentProject` as the client last read it. The server compares this value against the project's current `version`. If they match, the revision is created and the project's `version` advances. If another writer has already created a revision (or otherwise advanced the project) since the client last read it, the supplied value is stale, and the create is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412). No other endpoint in this API accepts or requires a version field in its request body; concurrency control applies to revision creation alone.

### 2.7. Monetary Values, Credits, and Precision

All monetary amounts in this system are integer counts of whole cents — fees, surcharges, quotes, invoices, charges, refunds, and net totals alike. Wherever a discount or rate is applied and the result is not already a whole number, the system rounds to whole cents using the **round-half-up** method (a value exactly halfway between two cents rounds up to the larger). The pricing rules in §3 are explicit about *when* rounding happens relative to summation, because for the document portion of an order each line is discounted and rounded **before** the lines are summed, not after. Counts of credits, clauses, questions, signers, and revisions are plain non-negative integers and need no rounding.

### 2.8. Referential Integrity and Left-to-Right Resolution

When a request names a resource by an identifier — whether in the URL path or in a foreign-key field of the body — the system resolves those identifiers and rejects the request with `ERR_NOT_FOUND` (HTTP 404) if any of them does not correspond to an existing resource. Path and body identifiers are validated left-to-right, so the first unresolved identifier determines the error. Beyond mere existence, certain creates require that the named references be mutually consistent — for example that a subscription belongs to the customer it is being spent on behalf of, or that a clause library actually exists for a project's document type and state. When references resolve individually but are inconsistent with one another, the request is rejected with `ERR_REFERENCE_INVALID` (HTTP 409). Well-formedness of the request body itself — required fields present, enum values within their allowed sets, a non-empty signer list — is enforced with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.9. Validation Ordering

When several checks could fail on a single request, they are evaluated in a fixed priority order so that the returned error is predictable. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of every referenced id (`ERR_NOT_FOUND`), then cross-reference consistency of body foreign keys (`ERR_REFERENCE_INVALID`), then request well-formedness and typing (`ERR_INVALID_REQUEST`). After those, the optimistic-concurrency check on revision creation (`ERR_STALE_PROJECT_VERSION`) is evaluated, followed by the state-validity check that the target resource is in a legal from-state for the requested transition (`ERR_INVALID_STATE`). Only once all of those pass does the system evaluate the domain-specific business rules — subscription-active gating, add-on election, completeness gates, review-in-progress gates, scheduling overlaps, credit availability, and the rest — which are described in §3 next to the workflows they guard. The practical consequence is that, for instance, a request that both targets a resource in the wrong state and would also violate a business rule surfaces the state error first.

### 2.10. Enumerations and Fixed Vocabularies

Several fields draw from fixed enumerations, and their exact spellings are part of the contract. A customer's `state_of_residence`, a clause template's `state_code`, a project's `state_code`, an attorney's `bar_state`, and a notary referral's `referral_state_code` are each one of the two-letter codes `CA`, `NY`, `TX`, or `FL`. A document family — `document_type` on clause templates and projects — is one of `WILL`, `LLC`, `POA`, or `LEASE`. A plan or subscription `tier` is one of `FREE`, `STANDARD`, or `PREMIUM`. The lifecycle states of each entity are likewise fixed strings, enumerated in the workflow sections that follow.

## 3. Business Logic & Workflows

### 3.1. Customers, Plans, and the Subscription Lifecycle

Everything begins with a `Customer`, created with an `email` (the login email, unique among customers), a `full_name` (the customer's legal name), and a `state_of_residence`. The state of residence matters downstream: a customer may only create projects governed by their own state.

Separately, a `PlatformAdmin` curates a catalog of subscription plans. A `SubscriptionPlan` is identified by its `tier` (unique across the catalog) and carries a `monthly_fee_cents` recurring fee, an `included_project_credits` allowance of document projects granted per active billing period, an `included_clause_count` describing how many assembled clauses are bundled before per-clause overage fees begin, a `subscription_discount_pct` applied to the document portion of an order, and a `review_discount_pct` applied to the attorney-review surcharge. Each fee is a non-negative integer cent amount, each included count is a non-negative integer, and each discount is a fraction between 0.0 and 1.0 inclusive, expressed to two decimals.

A customer enters a paid relationship by subscribing to a plan. Creating a `Subscription` takes a `customer_id` and a `plan_id`; the subscription copies the plan's `tier` into its own `tier` field at subscribe time, begins life in `PENDING_PAYMENT` status, and initializes its `credits_used` to zero and its `credits_remaining` to the plan's `included_project_credits`. A subscription whose `plan_id` and `customer_id` do not both resolve, or whose plan does not exist, is rejected before creation. A subscription is not spendable while `PENDING_PAYMENT`; it must first be activated.

Subscription status is driven exclusively by a `PlatformAdmin` through a dedicated transition action that carries the desired `to_status`. From `PENDING_PAYMENT` the subscription may move to `ACTIVE`, at which point it becomes spendable for project credits. An `ACTIVE` subscription may move to `PAST_DUE`, which gates paid features — specifically, an attorney-review request against a project of a non-`ACTIVE` subscription is refused (see §3.5). A `PAST_DUE` subscription may be cured back to `ACTIVE`, re-enabling those paid features; this `PAST_DUE → ACTIVE` revert may happen repeatedly over the subscription's life. From either `ACTIVE` or `PAST_DUE`, the subscription may be moved to `CANCELLED`, which is terminal. Each of these transitions requires the subscription to currently be in the corresponding from-state; an attempt from any other state is rejected with `ERR_INVALID_STATE`.

Cancelling a subscription is the origin of the deepest cascade in the system. When a subscription transitions to `CANCELLED` (whether from `ACTIVE` or `PAST_DUE` — both behave identically), every `DocumentProject` of that subscription whose status is one of `DRAFT`, `IN_PROGRESS`, `ASSEMBLED`, `IN_REVIEW`, `CHANGES_REQUESTED`, or `FINALIZED` is forced to `STORAGE_LOCKED`. Projects already in a terminal state (`STORED`, `ABANDONED`, or an existing `STORAGE_LOCKED`) are left untouched. Each project driven to `STORAGE_LOCKED` then runs its own downstream effects, described in §3.8.

### 3.2. Document Projects: Creation and the Credit Ledger

A `DocumentProject` is the customer's working folder for one document. A `Customer` creates one by supplying the owning `customer_id`, the funding `subscription_id`, the `document_type`, the governing `state_code`, and a human-readable `title`. The customer may also set `attorney_review_addon` (whether the paid attorney-review add-on is elected, defaulting to false when omitted). For lease documents only, the request may additionally carry `lease_property_ref` (an opaque property identifier used for term-overlap checks), `lease_start_date`, and `lease_end_date`; for every other document type these three fields are null.

Several consistency rules guard creation. The named `subscription_id` must belong to the named `customer_id`, and the project's `state_code` must equal the owning customer's `state_of_residence`; a violation of either is an `ERR_REFERENCE_INVALID`. Document projects consume subscription credits: a project may be created only if the funding subscription has at least one credit remaining — that is, its `credits_remaining` is one or greater. If no credit remains (`credits_remaining` is zero), creation is refused with `ERR_NO_CREDITS_REMAINING` (HTTP 402).

When a project is successfully created, three things happen together. The project is born in `DRAFT` status. The funding subscription's `credits_used` is incremented by one, the project's `credit_held` flag is set true to mark that it is holding one of that subscription's credits, and the subscription's `credits_remaining` is recomputed as the plan's `included_project_credits` minus the new `credits_used`. And an `Order` is created as a side effect, linked to this project by `document_project_id`, with every monetary field — `provisional_quote_cents`, `final_invoice_cents`, `amount_charged_cents`, `amount_refunded_cents`, and `net_collected_cents` — initialized to zero.

The credit relationship is a conserved quantity. The invariant the system maintains is that a subscription's `credits_used` always equals the number of that subscription's projects whose `credit_held` is true. A credit is returned to the pool only when a project is abandoned before it has been assembled: transitioning a project to `ABANDONED` from either `DRAFT` or `IN_PROGRESS` sets the project's `credit_held` to false, decrements the owning subscription's `credits_used` by one, and recomputes `credits_remaining`. A project abandoned this way is terminal. Note that abandonment is only offered from these two pre-assembly states; once a project has reached `ASSEMBLED` or beyond, its credit stays held.

### 3.3. The Questionnaire and Provisional Completeness

The guided experience runs through a one-to-one questionnaire. A `Customer` upserts the project's `QuestionnaireResponse` by submitting an `answers` map keyed by required-question key. The same upsert action both creates the response (the first time) and replaces it (subsequently); the persisted response is always one-to-one with its project via `document_project_id`. The GET questionnaire endpoint nonetheless returns a paginated array envelope (`response_type` `"array"`) containing the zero or one matching response for the project, not a bare object. The first successful upsert moves the project from `DRAFT` to `IN_PROGRESS`; every subsequent upsert leaves the project in `IN_PROGRESS` (a self-loop) while refreshing the answers.

Each upsert recomputes the project's `provisional_completeness`, which expresses how much of the required questionnaire is done. The denominator, captured on the response as `total_required_count`, is the total number of required questions for the project's document type: 8 for a `WILL`, 6 for an `LLC`, 4 for a `POA`, and 6 for a `LEASE`. The numerator, captured as `answered_required_count`, is the count of required questions that have a non-empty value in `answers`, but never more than the total — if a client somehow supplies more non-empty entries than there are required questions, the answered count is capped at the total. A value counts as non-empty unless it is `null`, an empty or whitespace-only string, or an empty list or empty object; any other value (including a number or boolean) counts as non-empty. The count is taken over every non-empty entry in the submitted `answers` map (before the cap), without regard to whether its key names a recognized required question. The project's `provisional_completeness` is then `answered_required_count` divided by `total_required_count`, a ratio between 0.0 and 1.0. Because every document type has at least one required question, the denominator is always at least one and the division is always defined.

### 3.4. Assembly: Clause Snapshotting and the Provisional Quote

Once the questionnaire is complete, the customer assembles the document. The `PlatformAdmin` maintains the clause library: each `ClauseTemplate` has a `clause_key` (stable within a document-type/state pairing, and unique together with `document_type` and `state_code`), a `document_type`, a `state_code`, an `is_mandatory` flag indicating whether the clause must be present for a valid document of that type and state, and the `body_text` prose that will be snapshotted at assembly.

Assembling a project advances it from `IN_PROGRESS` to `ASSEMBLED`. Two gates guard the action, and both must hold. First, the project's `provisional_completeness` must have reached completion — it must be at least 1.0; if the questionnaire is not fully answered, assembly is refused with `ERR_QUESTIONNAIRE_INCOMPLETE`. Second, at least one `ClauseTemplate` must exist for the project's `document_type` and `state_code` pairing; if the library is empty for that combination, assembly is refused with `ERR_NO_CLAUSE_TEMPLATES`. Assembly is of course only valid from `IN_PROGRESS`; from any other state it is an `ERR_INVALID_STATE`.

When assembly succeeds, the system creates one `AssembledClause` for every `ClauseTemplate` matching the project's `document_type` and `state_code`, copying each template's `body_text`, `clause_key`, and `is_mandatory` into the frozen clause and recording the originating template's id in `source_clause_template_id`. Each assembled clause also references its project through `document_project_id`. The project's `assembled_clause_count` is set to the number of `AssembledClause` rows just created. The system then recomputes the project's `assembled_completeness` and the order's `provisional_quote_cents`, both described next.

The **provisional quote** is the document portion of the price, and nothing more — no review surcharge, no notary fee. It is built from three lines, each discounted and rounded independently before the three are summed. The base line is the per-type base price: 4999 cents for a `WILL`, 9999 for an `LLC`, 3999 for a `POA`, and 2999 for a `LEASE`. The state line is the per-state surcharge: 1500 cents for `CA`, 1999 cents for `NY`, and 0 cents for both `TX` and `FL`. The extra-clause line covers overage: it is the number of assembled clauses beyond the plan's bundled allowance — that is, the project's `assembled_clause_count` minus the plan's `included_clause_count`, but never less than zero — multiplied by the extra-clause fee of 799 cents per clause. The plan's `subscription_discount_pct` is applied to each of these three lines individually: each line is multiplied by one minus the discount fraction, that product is rounded half-up to whole cents, and only then are the three rounded line amounts added together to give `provisional_quote_cents`.

### 3.5. Attorney Review: Request, Pricing, and Adjudication

A customer who elected the add-on can route an assembled draft to a licensed attorney. Attorneys themselves are onboarded by a `PlatformAdmin`; an `Attorney` record carries a `full_name` and a `bar_state`. A `Customer` requests a review by creating an `AttorneyReview` referencing the project under review via `document_project_id` and the chosen reviewer via `attorney_id`, together with the review's `window_start` and `window_end` — the time window, in UTC, during which the attorney is occupied with this matter.

Requesting a review advances the project from `ASSEMBLED` to `IN_REVIEW`, and three preconditions guard it. The project must currently be `ASSEMBLED` (otherwise `ERR_INVALID_STATE`). The project's `attorney_review_addon` must be true; a review requested on a project that never elected the add-on is refused with `ERR_REVIEW_ADDON_NOT_ELECTED`. And the project's owning subscription must be `ACTIVE` at request time; if the subscription is `PAST_DUE`, `PENDING_PAYMENT`, or `CANCELLED`, the request is refused with `ERR_SUBSCRIPTION_NOT_ACTIVE`. There is also a scheduling constraint: the proposed window must not collide with the attorney's existing commitments. The window is treated as the half-open interval running from `window_start` up to but not including `window_end`, and it must not overlap any other non-`CANCELLED` review already held by the same attorney; a back-to-back pairing where one window ends exactly as the next begins is allowed. The only review status excluded from this overlap set is `CANCELLED`: a review in any other status — `REQUESTED`, `ASSIGNED`, `IN_REVIEW`, `APPROVED`, or `CHANGES_REQUESTED` — continues to occupy its window for conflict purposes, so reaching a terminal `APPROVED` or `CHANGES_REQUESTED` state does not free the window for reuse by a new overlapping review. A collision is refused with `ERR_ATTORNEY_WINDOW_CONFLICT`.

On a successful request the review is created in `REQUESTED` and immediately auto-advanced to `ASSIGNED`, occupying the attorney's window. At the same moment the **review surcharge** is priced and charged. The surcharge is the standard review fee of 7500 cents, reduced by the plan's `review_discount_pct`: the fee is multiplied by one minus that discount fraction and rounded half-up to whole cents. The result is stored on the review as `surcharge_cents`, added to the order's `amount_charged_cents`, and the order's `net_collected_cents` is recomputed. Crucially, the review surcharge is charged here, at request time — not at finalization.

The assigned attorney works the review through a transition action carrying `to_status`. The acting attorney must be the review's own `attorney_id`, or the action is refused with `ERR_NOT_REVIEW_OWNER`. From `ASSIGNED` the attorney moves the review to `IN_REVIEW` to begin examining the draft. From `IN_REVIEW` the review branches two ways, and the branches are symmetric in importance. If the attorney **approves**, the review moves to `APPROVED` (a terminal state), the attorney is freed from actively examining the matter, and the project is driven back from `IN_REVIEW` to `ASSEMBLED` so it can be finalized — no money changes hands at approval, because the surcharge was already charged at request. (The review record itself is not mutated beyond this status change; because it is now `APPROVED` rather than `CANCELLED`, it remains a live record that still occupies its scheduling window for the overlap check of §3.5.) If instead the attorney **requests changes**, the review moves to `CHANGES_REQUESTED`, the attorney is freed from actively examining the matter, the project is driven from `IN_REVIEW` to `CHANGES_REQUESTED`, and the project's newest `DocumentRevision` (the one currently `FINAL`) is flipped to `SUPERSEDED` to reflect that the snapshot the attorney reviewed is no longer the live draft. Each branch requires the review to currently be `IN_REVIEW`.

A project sitting in `CHANGES_REQUESTED` reopens its revision loop: the customer transitions it back to `IN_PROGRESS` to make edits, retaining the project's accumulated `provisional_completeness`. This is the cyclic heart of the workflow — a project can travel `ASSEMBLED → IN_REVIEW → CHANGES_REQUESTED → IN_PROGRESS` and around again as many revision rounds as the work requires.

### 3.6. Revisions and Their Ordering

A `DocumentRevision` is an immutable, ordered snapshot of a project's assembled document. A `Customer` creates one against a project identified by `document_project_id`, and the create is guarded by optimistic concurrency: the request must carry `expected_document_project_version` matching the project's current `version`, failing with `ERR_STALE_PROJECT_VERSION` if stale (see §2.6). On creation the new revision is assigned a `revision_number` — a 1-based sequence within the project, ordered by creation time (`created_at` ascending) — and its `clause_snapshot_count` is set to the number of `AssembledClause` rows captured into the snapshot. The supplied `expected_document_project_version` is also retained verbatim on the created revision as a field of the same name. The new revision is the project's `FINAL` revision; any prior revision of the same project that was `FINAL` is flipped to `SUPERSEDED`, so exactly one revision per project is `FINAL` at a time. Creating a revision advances the project's `version` by one — which is precisely why a second writer working from a stale observed version is rejected.

A revision's `status` is therefore always either `FINAL` (the live snapshot) or `SUPERSEDED` (an older one, or one invalidated when an attorney requested changes per §3.5).

### 3.7. Finalization, Signing, Notarization, and Reminders

Once a project's draft is settled, the customer **finalizes** it. Finalization moves a project to `FINALIZED` from either `ASSEMBLED` or `CHANGES_REQUESTED`, carrying `to_status`. Two business gates apply when finalizing. The project's `assembled_completeness` must be at least 1.0 — meaning every mandatory clause required for the document is present — or the action is refused with `ERR_MANDATORY_CLAUSE_MISSING`. The `assembled_completeness` ratio is the count of mandatory `AssembledClause` rows on the project divided by the number of mandatory clause templates currently in the library for the project's `document_type` and `state_code`; if there are no mandatory templates the ratio is taken to be 1.0. Because the denominator is read live at finalize time while the numerator was snapshotted at assembly, an admin who adds a new mandatory `ClauseTemplate` after a project assembled will drive that project's `assembled_completeness` below 1.0 and block its finalization until it is reassembled. Additionally — and this gate applies specifically when finalizing a project that is in `ASSEMBLED` — finalization is blocked while any `AttorneyReview` for the project is still in `REQUESTED`, `ASSIGNED`, or `IN_REVIEW`; such an in-flight review yields `ERR_REVIEW_IN_PROGRESS`.

Finalization recomputes the order's `final_invoice_cents` as the sum of three lines. The document portion is recomputed exactly as the provisional quote was (the same three per-line-discounted-and-rounded lines from §3.4). The active review line is the sum of `surcharge_cents` over the project's `APPROVED` attorney reviews — cancelled reviews are excluded because their surcharge was refunded. The active notary line is the notary fee of 2500 cents if any `SignatureRequest` on a `FINAL` revision of the project has `notary_required` set true, and zero otherwise. The order's `amount_charged_cents` is additive across the lifecycle: the review surcharge was already added at review request, so finalization adds the document portion plus the notary line, and `net_collected_cents` is recomputed. For a project with one approved review and a notary-required envelope, this additive bookkeeping leaves `amount_charged_cents` equal to `final_invoice_cents`.

With the project `FINALIZED`, signing can begin. A `Customer` creates a `SignatureRequest` (an e-signature envelope) against the `FINAL` revision by `document_revision_id`, supplying an ordered, non-empty `signer_emails` list and optionally `notary_required` (defaulting to false). The envelope is born in `DRAFT` with `signed_count` at zero. The customer then sends it, transitioning `DRAFT → SENT` via `to_status`; sending requires that the referenced `DocumentRevision` still be `FINAL` (a `SUPERSEDED` revision yields `ERR_REVISION_SUPERSEDED`) and that the owning `DocumentProject` be `FINALIZED` (otherwise `ERR_PROJECT_NOT_FINALIZED`).

Signers then sign, one at a time, through a sign action carrying the signing `signer_email`. The email must be one of the invited `signer_emails`, or the request is refused with `ERR_SIGNER_NOT_INVITED`, and it must not already appear in `signed_emails`, or it is refused with `ERR_ALREADY_SIGNED`. Each valid signature appends the email to `signed_emails` and increments `signed_count`. While outstanding signers remain — that is, after a signature the `signed_count` is still below the number of invited signers — the envelope sits in `PARTIALLY_SIGNED`. When the final outstanding signer signs and `signed_count` reaches the length of `signer_emails`, the envelope becomes `COMPLETED`; a single-signer envelope goes straight from `SENT` to `COMPLETED` on its sole signature. Completion bubbles up: the owning `DocumentProject` is driven from `FINALIZED` to `SIGNED`, and that transition in turn schedules an `UpdateReminder`. An envelope may also be voided from `DRAFT`, `SENT`, or `PARTIALLY_SIGNED`, moving it to the terminal `VOIDED` state via `to_status`.

If the envelope is flagged `notary_required`, the customer may create a `NotaryReferral` against it by `signature_request_id`, choosing a `referral_state_code` whose notary network the customer is referred to. A referral may only be created for an envelope whose `notary_required` is true; a referral against an envelope that does not require notarization is refused with `ERR_NOTARY_NOT_REQUIRED`. A notary referral is born — and stays — in the terminal `REFERRED` status.

A signed project enters secure storage: the customer transitions it from `SIGNED` to `STORED`, and any scheduled reminder remains in place. The customer-driven project transition endpoint accepts only the `to_status` values `IN_PROGRESS` (the `CHANGES_REQUESTED` reopen), `FINALIZED`, `STORED`, and `ABANDONED`; the server-driven targets `SIGNED` and `STORAGE_LOCKED` (and any other status) are not reachable through it and a request naming one is refused with `ERR_INVALID_STATE`. The `UpdateReminder` scheduled when the project reached `SIGNED` carries a `due_at` set to the moment of signing plus the reminder interval of 90 days, and is born `SCHEDULED`. The "moment of signing" is the current logical clock instant when the clock has been set, and the server's wall-clock instant otherwise. A `PlatformAdmin` controls the logical clock and the reminder sweep: the admin sets the system clock to a fixed UTC instant via `to_iso8601`, then runs a sweep that fires due reminders. The sweep transitions every `SCHEDULED` reminder whose `due_at` is at or before the current clock to `SENT`; a reminder whose `due_at` is still in the future relative to the clock is not yet due and is simply left `SCHEDULED` by the sweep (a no-op for that reminder), not transitioned and not errored. The sweep itself always succeeds. There is no endpoint that dispatches a single reminder directly, so although `ERR_REMINDER_NOT_DUE` is reserved for a not-yet-due dispatch, no operation in this API actually returns it. A reminder may otherwise end up `CANCELLED` only through the storage-lock cascade described next.

### 3.8. Lease Term Conflicts and the Storage-Lock Cascade

Lease projects carry one extra guard at creation. Because a single property cannot be under two overlapping leases, creating a `LEASE` project checks the proposed term — the closed interval from `lease_start_date` to `lease_end_date` — against every existing non-`ABANDONED` `LEASE` project sharing the same `lease_property_ref`. The terms must not overlap, and consecutive terms must additionally be separated by a turnover buffer of 7 days between one term's end and the next term's start; a term that overlaps an existing term, or that falls within the buffer gap of one, is refused with `ERR_LEASE_TERM_OVERLAP`. Non-lease projects skip this check entirely, as does a `LEASE` project whose creation request omits any of `lease_property_ref`, `lease_start_date`, or `lease_end_date` — the overlap check runs only when all three are supplied, and is compared against existing `LEASE` projects whose stored `lease_property_ref` equals the new project's.

The **storage-lock cascade** is the multi-hop consequence of a subscription cancellation (§3.1). Its origin is the subscription moving to `CANCELLED`; its first hop drives each eligible project (those in `DRAFT`, `IN_PROGRESS`, `ASSEMBLED`, `IN_REVIEW`, `CHANGES_REQUESTED`, or `FINALIZED`) to `STORAGE_LOCKED`, a terminal state. Each project entering `STORAGE_LOCKED` then performs its own hop: every `AttorneyReview` of that project still in `REQUESTED`, `ASSIGNED`, or `IN_REVIEW` is transitioned to `CANCELLED`. And each review so cancelled performs the final hop — a refund: the review's `surcharge_cents` is added to the project's order's `amount_refunded_cents`, the order's `net_collected_cents` is recomputed, and the attorney's window is released. Separately, when a project is locked, any `UpdateReminder` of that project still `SCHEDULED` is moved to `CANCELLED` so it can never fire against a locked document.

This refund-on-cancellation closes the **money-conservation** loop. The system guarantees that an order's `net_collected_cents` always equals its `amount_charged_cents` minus its `amount_refunded_cents`, and that this net equals the document portion charged plus the sum of `surcharge_cents` across the project's non-`CANCELLED` reviews plus any active notary line. A review surcharge added at request and later refunded when the review is cancelled through the cascade nets to zero, exactly as a fully-settled forward-and-compensating pair should.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state transitions, questionnaire upserts, assembly, signing, and the administrative clock and sweep actions — return a `200 OK` status code. Reading a resource or a list returns `200 OK`. Request bodies, response bodies, and side effects are not restated here; they are defined in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/legal/customers` | Create a Customer | Customer, PlatformAdmin |
| GET | `/legal/customers/{id}` | Get a Customer | Customer, PlatformAdmin |
| POST | `/legal/subscription-plans` | Create a SubscriptionPlan | PlatformAdmin |
| GET | `/legal/subscription-plans/{id}` | Get a SubscriptionPlan | Customer, Attorney, PlatformAdmin |
| POST | `/legal/subscriptions` | Subscribe a customer to a plan | Customer, PlatformAdmin |
| GET | `/legal/subscriptions/{id}` | Get a Subscription | Customer, PlatformAdmin |
| GET | `/legal/subscriptions` | List subscriptions, filterable by customer and/or plan | Customer, PlatformAdmin |
| POST | `/legal/subscriptions/{id}/transition` | Transition a subscription's status | PlatformAdmin |
| POST | `/legal/clause-templates` | Create a state-specific ClauseTemplate | PlatformAdmin |
| GET | `/legal/clause-templates/{id}` | Get a ClauseTemplate | Customer, Attorney, PlatformAdmin |
| GET | `/legal/clause-templates` | List clause templates, filterable by type and/or state | Customer, Attorney, PlatformAdmin |
| POST | `/legal/document-projects` | Create a DocumentProject | Customer |
| GET | `/legal/document-projects/{id}` | Get a DocumentProject | Customer, Attorney, PlatformAdmin |
| GET | `/legal/document-projects` | List projects, filterable by customer and/or subscription | Customer, Attorney, PlatformAdmin |
| PUT | `/legal/document-projects/{id}/questionnaire` | Upsert the project's questionnaire answers | Customer |
| GET | `/legal/document-projects/{id}/questionnaire` | Get the project's questionnaire response | Customer, Attorney, PlatformAdmin |
| POST | `/legal/document-projects/{id}/assemble` | Assemble state-specific clauses into the project | Customer |
| POST | `/legal/document-projects/{id}/transition` | Transition a project's status | Customer |
| GET | `/legal/assembled-clauses/{id}` | Get an AssembledClause | Customer, Attorney, PlatformAdmin |
| GET | `/legal/assembled-clauses` | List assembled clauses for a project | Customer, Attorney, PlatformAdmin |
| POST | `/legal/document-revisions` | Snapshot the project's document as a new FINAL revision | Customer |
| GET | `/legal/document-revisions/{id}` | Get a DocumentRevision | Customer, Attorney, PlatformAdmin |
| GET | `/legal/document-revisions` | List revisions for a project | Customer, Attorney, PlatformAdmin |
| POST | `/legal/attorneys` | Create an Attorney | PlatformAdmin |
| GET | `/legal/attorneys/{id}` | Get an Attorney | Customer, Attorney, PlatformAdmin |
| POST | `/legal/attorney-reviews` | Request an attorney review for an assembled project | Customer |
| GET | `/legal/attorney-reviews/{id}` | Get an AttorneyReview | Customer, Attorney, PlatformAdmin |
| GET | `/legal/attorney-reviews` | List reviews, filterable by project and/or attorney | Customer, Attorney, PlatformAdmin |
| POST | `/legal/attorney-reviews/{id}/transition` | Attorney advances the review | Attorney |
| POST | `/legal/signature-requests` | Create an e-signature envelope for a FINAL revision | Customer |
| GET | `/legal/signature-requests/{id}` | Get a SignatureRequest | Customer, Attorney, PlatformAdmin |
| GET | `/legal/signature-requests` | List signature requests for a revision | Customer, Attorney, PlatformAdmin |
| POST | `/legal/signature-requests/{id}/transition` | Send or void an envelope | Customer |
| POST | `/legal/signature-requests/{id}/sign` | A signer signs the envelope | Customer |
| POST | `/legal/notary-referrals` | Create a notary referral for an envelope | Customer |
| GET | `/legal/notary-referrals/{id}` | Get a NotaryReferral | Customer, PlatformAdmin |
| GET | `/legal/notary-referrals` | List notary referrals for a signature request | Customer, PlatformAdmin |
| GET | `/legal/orders/{id}` | Get an Order | Customer, PlatformAdmin |
| GET | `/legal/orders` | List orders for a project | Customer, PlatformAdmin |
| GET | `/legal/update-reminders/{id}` | Get an UpdateReminder | Customer, PlatformAdmin |
| GET | `/legal/update-reminders` | List update reminders for a project | Customer, PlatformAdmin |
| POST | `/legal/_clock/set` | Set the system clock to a fixed UTC instant | PlatformAdmin |
| POST | `/legal/_reminders/dispatch_due` | Fire every due scheduled reminder | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_REFERENCE_INVALID` | 409 Conflict |
| `ERR_STALE_PROJECT_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 403 Forbidden |
| `ERR_REVIEW_ADDON_NOT_ELECTED` | 409 Conflict |
| `ERR_QUESTIONNAIRE_INCOMPLETE` | 409 Conflict |
| `ERR_NO_CLAUSE_TEMPLATES` | 409 Conflict |
| `ERR_MANDATORY_CLAUSE_MISSING` | 409 Conflict |
| `ERR_REVIEW_IN_PROGRESS` | 409 Conflict |
| `ERR_ATTORNEY_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_LEASE_TERM_OVERLAP` | 409 Conflict |
| `ERR_REVISION_SUPERSEDED` | 409 Conflict |
| `ERR_PROJECT_NOT_FINALIZED` | 409 Conflict |
| `ERR_NOT_REVIEW_OWNER` | 403 Forbidden |
| `ERR_SIGNER_NOT_INVITED` | 409 Conflict |
| `ERR_ALREADY_SIGNED` | 409 Conflict |
| `ERR_NOTARY_NOT_REQUIRED` | 409 Conflict |
| `ERR_NO_CREDITS_REMAINING` | 402 Payment Required |
| `ERR_REMINDER_NOT_DUE` | 409 Conflict |

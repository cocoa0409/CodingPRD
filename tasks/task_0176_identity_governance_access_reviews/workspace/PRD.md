# Identity Governance API — Product Requirements Document

## 1. Introduction

Enterprises grant their workforce — and their machine accounts — thousands of fine-grained permissions across dozens of target systems, and every one of those permissions is an audit liability if no one can say who has it, why they were given it, and whether it is still needed. This document specifies the Identity Governance API, a system of record for the full access lifecycle: a catalog of entitlements and the business roles that bundle them, the request-and-approval workflow through which workforce identities acquire access, the segregation-of-duties controls that keep toxic permission combinations apart, the periodic certification campaigns through which managers re-attest that standing access is still warranted, and the provisioning and deprovisioning machinery that keeps a target system's reality aligned with the governance decisions recorded here.

The API is built for auditability first. Every consequential action — a grant going live, a grant being torn down, a request being decided, an identity being disabled, an item being certified, an orphan account surfacing — leaves an immutable evidence record. Risk is quantified continuously: each identity carries a live risk score reflecting the access it actually holds, and a forward-looking projection of the risk it would carry if its pending requests were approved. The system enforces separation between the person who asks for access and the person who grants it, demands a second approver for privileged bundles, and prevents an auditor from overwriting a colleague's concurrent change to the same identity. The remainder of this document defines the global contracts that all endpoints share, the business logic and state machines that govern each entity, the full endpoint surface, and the catalogue of error conditions.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting operator, and `X-User-Role`, which declares the operational capacity under which they are acting. If either header is missing, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly five roles, spelled precisely as follows: `CatalogAdmin`, `AccessManager`, `AccessApprover`, `CampaignAdmin`, and `Certifier`. When an authenticated operator attempts an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The roles carve up responsibility along separation-of-duties lines. A `CatalogAdmin` owns the configuration catalog — entitlements, roles, and segregation-of-duties policies. An `AccessManager` provisions identities and direct grants, raises access requests, and disables, enables, or deprovisions identities; in the request workflow the `AccessManager` is the requester. An `AccessApprover` decides access requests and may not be the requester nor the target of the request they decide. A `CampaignAdmin` creates, launches, and closes certification campaigns. A `Certifier` reviews individual certification items, certifying or revoking the underlying grants.

For each of these five roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server records it where a workflow demands a durable actor — for example as `requester_user_id` on the access request a manager raises, as `decided_by_user_id` on a request or item once an approver or certifier decides it, and as `actor_user_id` on every audit evidence record — but it never compares `X-User-ID` to any entity's `id` as an ownership check. The one place identity comparison matters is segregation of duties, described in §3, where the approver's `X-User-ID` is compared against the stored `requester_user_id` and against the target identity, not against any notion of resource ownership.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0.

Unless a specific workflow states otherwise, every list endpoint returns resources sorted by their creation timestamp, `created_at`, in ascending order.

Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources in this system are full first-class entities that carry a standard set of system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording first creation; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation; and `version`, an integer that begins at its initial value and increments by one on every mutation of the resource. These four fields apply to entitlements, roles, segregation-of-duties policies, identities, access requests, grants, certification campaigns, and certification items.

One entity is deliberately different. An audit evidence record carries only `id` and `created_at`. Because audit evidence is append-only and immutable once written, it has no `updated_at` and no `version` field at all — it is never modified after creation, so neither field exists on it.

Whenever a computed or derived field on an entity changes as the downstream consequence of some action — for instance an identity's grant counters or risk scores being recomputed after a grant activates — that recomputation is itself a mutation of the affected resource: its `updated_at` is refreshed and its `version` increments accordingly.

### 2.5. Nested Resource Retrieval and Reference Resolution

The entity model is flat: entities are peers linked by foreign keys rather than owned through deep URL chains. A handful of read endpoints nonetheless address a resource through a parent path segment — listing the grants or audit evidence of a particular identity, or listing the items of a particular campaign. For any path that carries an identifier, the system validates identifiers strictly left to right: the parent identifier in the path is resolved first, and if it does not correspond to an existing resource the request is rejected with `ERR_NOT_FOUND` before any child lookup or body processing occurs. The same `ERR_NOT_FOUND` governs body foreign keys: after the path resolves, any referenced resource id supplied in the request body that does not resolve to an existing resource is rejected with `ERR_NOT_FOUND`.

### 2.6. Validation Order and Precedence

When several conditions could each reject a request, they are evaluated in a fixed precedence so that the same input always produces the same error. Authentication is checked first: a request missing either auth header is rejected with `ERR_UNAUTHENTICATED` before anything else. Authorization is checked second: a present-but-impermissible role on a mutating endpoint is rejected with `ERR_FORBIDDEN_ROLE`. Existence is checked third: path identifiers (left to right) and then body foreign keys must resolve, or the request fails with `ERR_NOT_FOUND`. Malformed bodies or missing required fields are rejected with `ERR_VALIDATION`, and an enum field carrying a value outside its declared set is rejected with `ERR_INVALID_ENUM`. State validity is checked fourth: if the target resource is not in a state from which the requested transition is defined, the request is rejected with `ERR_INVALID_STATE`. Only after these structural gates pass does the system evaluate the business-safety, referential, constraint, and temporal rules described throughout §3; where two such rules could both apply to one endpoint, the per-endpoint ordering is stated alongside the workflow that uses it.

### 2.7. Risk Scoring, Privilege Surcharge, and Derived-Field Reconciliation

Each identity carries two risk numbers and three reconciled counters that the system keeps continuously consistent with the grants the identity holds. The counters are `active_grant_count` (how many of the identity's grants are currently live), `privileged_entitlement_count` (how many distinct privileged entitlements the identity holds through live grants), and the two scores `effective_risk_score` and `projected_risk_score`. All five are conserved quantities: they are never set by a client and are recomputed by the system every time a grant activates, a grant is revoked, a request changes the pending set, or an identity is disabled.

Risk is measured in integer points and is never rounded, because every input is itself an integer. The **effective risk score** reflects only access the identity actually holds right now. Its base is the sum of the `risk_weight` of every entitlement the identity holds through a grant whose lifecycle is `ACTIVE`. On top of the base sits a stepped **privilege surcharge**: count the distinct privileged entitlements held through active grants, cap that count at three, and add 25 points for each counted privileged entitlement. In other words the surcharge is 25 points multiplied by the smaller of the privileged count and three — so zero privileged entitlements add nothing, one adds 25, two add 50, three add 75, and four or more still add only 75. The effective risk score is the base plus this surcharge. Each individual active grant's `risk_contribution` is exactly the `risk_weight` of its entitlement; the surcharge is an identity-level addition and is not distributed across the individual grants.

The **projected risk score** is a forward-looking estimate of the risk the identity would carry if every one of its currently `SUBMITTED` access requests were approved. Start from the same active-grant base used by the effective score. Then form the set of pending entitlements: take the union of all entitlements bundled by the role of each access request for this identity whose status is `SUBMITTED`, and remove from that set any entitlement the identity already holds through an active grant. Sum the `risk_weight` of the entitlements remaining in that pending set to get the pending base. For the privilege surcharge in the projection, count the distinct privileged entitlements across the union of the active-grant entitlements and the pending entitlements, cap that count at three, and add 25 points per counted privileged entitlement. The projected risk score is the active-grant base plus the pending base plus this projected surcharge. When an identity has no submitted requests, its pending set is empty and its projected risk score equals its effective risk score.

A risk threshold of 100 points marks the boundary of high risk. When a newly activated privileged grant pushes an identity's effective risk score across that high-risk boundary, the system flags that newest privileged grant for review, as detailed in §3.

### 2.8. Optimistic Concurrency on Identities

Three operations against an identity mutate it in ways that another operator could be racing to change, so they are guarded by optimistic concurrency control. Directly provisioning a grant for an identity, disabling an identity, and enabling an identity each require the caller to supply `expected_identity_version`, carrying the `version` of the target identity the caller last observed. The server compares that value to the identity's current `version`; if they do not match — because another writer has advanced the identity's version since the caller read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

The direct-grant case is the motivating one. A direct re-grant of the same entitlement legitimately supersedes any prior standing grant under the product's re-provisioning semantics, so a create that observes the identity's current, unchanged state would itself succeed. The version guard exists to reject precisely the create whose view of the identity is stale: if another writer has already provisioned against this identity and bumped its `version`, a request still carrying the old `expected_identity_version` is refused with `ERR_STALE_VERSION` so the caller cannot act on an identity it has not re-read. Operations not in this set do not carry a version field and are not subject to this check.

### 2.9. Cascades, Audit Evidence, and Immediate Consistency

Many actions in this system mutate more than one entity in a single immediate, fully-consistent step. Approving a request creates and activates grants and recomputes the target identity's counters and scores; disabling an identity tears down all of its active grants; closing a campaign auto-revokes its undecided items and the grants behind them; revoking a certification item revokes the grant it covers. Each of these cascades is spelled out in the workflow that triggers it in §3, and each downstream entity it touches has its own `updated_at` and `version` advanced as part of the same operation.

Consequential actions also leave immutable audit evidence. An audit event records the `subject_identity_id` it concerns, an `event_type` drawn from the fixed set `GRANT_ACTIVATED`, `GRANT_REVOKED`, `REQUEST_APPROVED`, `REQUEST_REJECTED`, `IDENTITY_DISABLED`, `ITEM_CERTIFIED`, and `ORPHAN_DETECTED`, an `actor_user_id` identifying the operator whose action produced the record (or the literal value `system` when the record is the product of an automatic cascade rather than a direct operator action), and a human-readable `detail` summary. Audit evidence is append-only: once written it is never updated or deleted.

## 3. Business Logic & Workflows

### 3.1. Building the Catalog: Entitlements, Roles, and Toxic Pairs

The catalog is the configuration foundation, owned entirely by a `CatalogAdmin`. The finest-grained unit is the **entitlement**, the thing that actually provisions into a target system. An entitlement is created with a catalog display `name` and a `system_code` naming the target system it provisions into (such as `SAP_FI`). Two optional attributes shape its risk behavior: `is_privileged`, a boolean that defaults to false and marks the entitlement as conferring privileged or administrative access, and `risk_weight`, the base risk points holding it contributes, which defaults to 10 and must be an integer between 0 and 100 inclusive. Every entitlement carries a `status` that begins as `ACTIVE`; an admin may archive it, moving its `status` to `ARCHIVED`. An `ARCHIVED` entitlement can no longer be newly requested or granted.

A **role** is a named bundle of entitlements — a business-meaningful package such as "Accounts Payable Clerk." A role is created with a `name` and an `entitlement_ids` array listing the entitlements it bundles; this is a membership list rather than a scalar reference, and at create time every element must reference an existing entitlement whose `status` is `ACTIVE`. The system computes a `requires_dual_approval` flag on the role: it is true exactly when the role bundles at least one entitlement whose `is_privileged` is true, and it is the flag that later forces a second approver on access requests for this role. A role's `status` begins as `ACTIVE` and an admin may retire it, moving `status` to `RETIRED`; a `RETIRED` role can no longer back new access requests.

To keep dangerous permission combinations apart, a `CatalogAdmin` defines **segregation-of-duties policies**. Each such policy has a `name` and names a toxic pair of entitlements through `entitlement_a_id` and `entitlement_b_id`; the two must differ, and a policy whose `entitlement_a_id` equals its `entitlement_b_id` is rejected with `ERR_SOD_PAIR_INVALID`. A policy's `severity` defaults to `HARD`: a `HARD` policy blocks any grant that would complete the toxic pair, whereas a `SOFT` policy records the violation but lets it through when an explicit justification is supplied. A policy's `status` begins as `ACTIVE`, and only `ACTIVE` policies are evaluated; an admin may set it to `DISABLED` to take it out of evaluation.

### 3.2. Identities, Direct Grants, and the Orphan Account

A workforce identity is the subject of all access. An `AccessManager` creates an **identity** with a `display_name`, a unique login `email`, and an optional `is_human` flag that defaults to true; setting `is_human` to false marks the record as a service or system account. A new identity starts with `status` equal to `ACTIVE` and all of its computed counters and scores at zero. The system also maintains an `is_orphan` flag on every identity: it is true exactly when the identity's `status` is `ACTIVE`, its `is_human` is false, and its `active_grant_count` is zero — that is, a live non-human account that holds no live access. A non-human identity with no grants is therefore orphaned the moment it is created, and identity listing supports orphan-account discovery directly.

Access most commonly arrives through the approval workflow, but an `AccessManager` may also provision a **grant** directly against an identity as an administrative action. A direct grant names the `entitlement_id` to confer and must carry `expected_identity_version` for the concurrency check described in §2.8. A direct grant may optionally be time-boxed as a just-in-time privileged grant by setting `is_just_in_time` to true and supplying `effective_from` and `effective_until` — the ISO 8601 UTC start and the exclusive end of the privileged window — where `effective_until` must be strictly after `effective_from`; for a standing (non-JIT) grant both window fields are null. A direct grant records its `identity_id`, its `entitlement_id`, and a `source_request_id` that is null for a direct admin grant (it carries the approved request's id only when the grant was spawned by an approval). When a direct grant is created it begins life in the provisioning stage and immediately activates, as described in §3.5, incrementing the identity's version by one as part of the operation.

Just-in-time windows for the same identity-and-entitlement combination may not overlap. When a direct just-in-time grant is created, the system checks the proposed window against every other just-in-time grant of the same identity and entitlement; treating each window as the half-open interval from `effective_from` up to but not including `effective_until`, two windows that merely touch at an endpoint are allowed, but any genuine overlap is rejected with `ERR_JIT_WINDOW_OVERLAP`. The window only gates privileged use; it does not gate activation, so a just-in-time grant activates immediately regardless of whether the current clock falls inside its window.

An `AccessManager` governs an identity's lifecycle through three further actions. **Disabling** an identity moves its `status` from `ACTIVE` to `DISABLED`; it is OCC-guarded and is examined in detail in §3.6. **Enabling** a disabled identity moves its `status` from `DISABLED` back to `ACTIVE`, is likewise OCC-guarded, and pointedly does not resurrect any previously revoked grants — the identity comes back with an `active_grant_count` of zero, which makes a non-human identity an orphan again. **Deprovisioning** moves a `DISABLED` identity to the terminal `DEPROVISIONED` status; it is permitted only from `DISABLED` (otherwise `ERR_INVALID_STATE`) and only when the identity's `active_grant_count` is already zero, failing with `ERR_IDENTITY_HAS_ACTIVE_GRANTS` if any live grant remains.

### 3.3. Raising and Submitting Access Requests

An **access request** is the formal ask for an identity to receive a role's worth of access. An `AccessManager` raises one by supplying the `identity_id` it is for, the `role_id` being requested, and a free-text `justification`; an optional `sod_override_justification` may be supplied here as well, though it only matters at approval time. The request is created in `DRAFT` status, and the raising manager's `X-User-ID` is stored as `requester_user_id` — the anchor for the separation-of-duties checks that follow. Each request also carries a computed `sod_conflict_detected` flag and, once decided, a `decided_by_user_id`.

Submitting a request advances it to `SUBMITTED`. Submission is allowed from `DRAFT` and again from `RETURNED` — the latter is a deliberate revision loop, so a returned request can be resubmitted any number of times. Submission enforces three preconditions: the target identity's `status` must be `ACTIVE`, or the request is rejected with `ERR_IDENTITY_NOT_ACTIVE`; the requested role's `status` must be `ACTIVE`, or the request is rejected with `ERR_ROLE_RETIRED`; and on the first submission out of `DRAFT`, every entitlement bundled by the role must have `status` equal to `ACTIVE`, or the request is rejected with `ERR_ENTITLEMENT_ARCHIVED` (the resubmission out of `RETURNED` re-checks identity and role status).

Submission has two side effects. First, it computes `sod_conflict_detected` by evaluating the toxic pairs: take the entitlements bundled by the requested role and the entitlements the identity already holds through active grants, and for each `ACTIVE` segregation-of-duties policy, check whether — once the requested access were granted — the identity would hold both sides of the policy's pair. Concretely, form the union of the requested entitlements and the held entitlements; a policy is in conflict when both its `entitlement_a_id` and its `entitlement_b_id` are members of that union (one side may already be held while the other comes from the request, or both may come from a multi-entitlement role). The flag `sod_conflict_detected` is true when at least one `ACTIVE` policy is in conflict. Second, submission recomputes the target identity's `projected_risk_score`, which now includes this submitted request's role entitlements per §2.7.

Returning a submitted request is an approver's action: it moves the request from `SUBMITTED` back to `RETURNED`. The returning approver's `X-User-ID` must not equal the request's `requester_user_id`, or the action is rejected with `ERR_SOD_SELF_ACTION`. Returning recomputes the identity's `projected_risk_score`, because the request no longer counts as pending while it sits in `RETURNED`.

### 3.4. Deciding Access Requests: Separation of Duties, Dual Approval, and SoD Conflicts

An `AccessApprover` decides a `SUBMITTED` request by either approving or rejecting it; both are terminal. Rejection moves the request to `REJECTED`, requires that the rejecter's `X-User-ID` differ from the `requester_user_id` (else `ERR_SOD_SELF_ACTION`), stamps `decided_by_user_id` with the approver's `X-User-ID`, writes an audit event of type `REQUEST_REJECTED`, and recomputes the identity's `projected_risk_score` since the request is no longer pending.

Approval moves the request to `APPROVED` and is the most heavily guarded transition in the system. Its preconditions are evaluated in the following order. First, the structural state gate of §2.6 applies — the request must be `SUBMITTED`. Then the separation-of-duties identity checks apply: the approver's `X-User-ID` must not equal the request's `requester_user_id`, and the approver's `X-User-ID` must not equal the target identity — either violation is rejected with `ERR_SOD_SELF_ACTION`. Next the target identity's `status` must be `ACTIVE`, or approval fails with `ERR_IDENTITY_NOT_ACTIVE`. Next, dual approval is enforced: if the requested role's `requires_dual_approval` is true, the approval request body must carry `second_approver_confirmed` equal to true, or the request is rejected with `ERR_DUAL_APPROVAL_REQUIRED`. Finally the segregation-of-duties conflict gate applies, re-evaluating the toxic pairs exactly as at submission: if any `ACTIVE` `HARD` policy is in conflict, approval is blocked outright with `ERR_SOD_CONFLICT`; if the only conflicts present are `SOFT`, approval may proceed but only when a non-empty `sod_override_justification` accompanies it, and a missing or empty override justification in the presence of a soft conflict is rejected with `ERR_SOD_OVERRIDE_REQUIRED`.

Once those gates pass, approval performs a depth-three cascade. The approver's `X-User-ID` is recorded as `decided_by_user_id`. For each entitlement bundled by the role, the system creates one grant in the provisioning stage and then auto-advances each new grant to active; each activation recomputes the identity's `active_grant_count`, `privileged_entitlement_count`, and `effective_risk_score` as described in §3.5. If, as a result of these activations, the identity's `effective_risk_score` crosses the high-risk threshold of 100 points, the newest privileged grant has its review dimension set to `FLAGGED`. An audit event of type `REQUEST_APPROVED` is appended. Finally the identity's `projected_risk_score` is recomputed: with the request no longer pending, its pending portion is cleared and the projection now equals the effective score.

### 3.5. The Grant: Two Parallel State Dimensions

A **grant** is the atom of access — exactly one entitlement conferred on exactly one identity. It records its `identity_id`, its `entitlement_id`, its `source_request_id`, the just-in-time fields `is_just_in_time`, `effective_from`, and `effective_until`, and a computed `risk_contribution`. Crucially, a grant carries two independent state dimensions that evolve in parallel: a `lifecycle_status` describing whether the access is live, and a `review_status` describing where the grant stands in certification. Movement along one dimension does not by itself move the other.

The lifecycle dimension runs `PROVISIONING` → `ACTIVE` → `REVOKED`, with `REVOKED` terminal. Every grant — whether spawned by an approval cascade or created as a direct admin grant — is born in `PROVISIONING` and is immediately auto-activated by the system to `ACTIVE`. For a just-in-time grant, activation does not require the current clock to fall within the privileged window; the window gates use, not activation. Activation has a precise set of side effects: it increments the owning identity's `active_grant_count` by one; if the grant's entitlement is privileged it increments `privileged_entitlement_count` by one (counting the distinct entitlement); it recomputes the identity's `effective_risk_score` and `is_orphan`; and it appends an audit event of type `GRANT_ACTIVATED`.

A live grant leaves the system by being revoked, moving `lifecycle_status` from `ACTIVE` to `REVOKED`. Revocation can be reached three ways: an `AccessManager` revoking the grant directly, the cascade from disabling the identity, or the cascade from a certification item being revoked. In every case the grant must currently be `ACTIVE` to be revoked, or the attempt fails with `ERR_INVALID_STATE`. Revocation's side effects mirror activation's in reverse: it decrements the identity's `active_grant_count` by one; if the entitlement is privileged and no other active grant of that same entitlement remains for the identity, it decrements `privileged_entitlement_count` by one; it recomputes the identity's `effective_risk_score` and `is_orphan`; and it appends an audit event of type `GRANT_REVOKED`.

The review dimension runs across `NOT_DUE`, `UNDER_REVIEW`, `CERTIFIED`, and `FLAGGED`, and it changes only through certification activity (or the high-risk auto-flag). A grant begins at `NOT_DUE`. When a certification campaign launches and enrolls a live grant, that grant moves `NOT_DUE` → `UNDER_REVIEW` — a parallel-dimension change that leaves its `lifecycle_status` untouched (enrollment requires the grant be `ACTIVE`). From `UNDER_REVIEW`, certifying the item bubbles the grant to `CERTIFIED`, while revoking the item — or the high-risk surcharge auto-flagging a freshly activated privileged grant — moves it to `FLAGGED`. The crucial distinction between the two `UNDER_REVIEW` exits is their effect on lifecycle: reaching `CERTIFIED` keeps the grant live and changes nothing on the lifecycle dimension, whereas reaching `FLAGGED` by way of an item revoke additionally cascades the grant's `lifecycle_status` from `ACTIVE` to `REVOKED` together with the full revoke side-effect set above. The high-risk auto-flag that sets `FLAGGED` at activation, by contrast, leaves the grant live.

### 3.6. Disabling and Tearing Down an Identity

Disabling an identity is the deprovisioning hinge of the whole system. An `AccessManager` disables an identity that is currently `ACTIVE` — any other starting status yields `ERR_INVALID_STATE` — and must supply `expected_identity_version` matching the identity's current `version`, failing with `ERR_STALE_VERSION` if it does not. Disabling performs a depth-two cascade: every grant for this identity whose `lifecycle_status` is `ACTIVE` is transitioned `ACTIVE` → `REVOKED`, and each such revoke runs its full side-effect set — decrementing `active_grant_count` and, where appropriate, `privileged_entitlement_count`, and recomputing `effective_risk_score`. An audit event of type `IDENTITY_DISABLED` is appended. Because every active grant is torn down, once the cascade settles the identity's `active_grant_count` is zero and its `effective_risk_score` is zero. This is exactly the precondition that later lets the identity be deprovisioned, and it is why re-enabling a disabled identity brings it back with no access at all.

### 3.7. Certification Campaigns and Their Items

Periodic certification is how the organization re-attests that standing access is still warranted. A `CampaignAdmin` creates a **certification campaign** with a `name`, a `scope_role_id` naming the role whose granted entitlements the campaign will review, and a review window bounded by `review_window_start` and `review_window_end` (ISO 8601 UTC, inclusive on both ends, with the end required to be on or after the start). A campaign begins in `DRAFT` status with its computed `posture` at `OPEN`. The campaign also exposes computed reporting fields: `item_count`, `completion_pct`, `projected_revocation_count`, and `realized_revocation_count`.

Launching a campaign moves it `DRAFT` → `ACTIVE`. Two scheduling guards protect the launch, both of which surface as `ERR_CAMPAIGN_WINDOW_OVERLAP`: no other campaign for the same `scope_role_id` may currently be in `ACTIVE` status, and this campaign's `review_window_start` must be on or after the prior `CLOSED` campaign's `review_window_end` for the same `scope_role_id` plus a one-day buffer. The launch also requires the scope role's `status` to be `ACTIVE`, failing with `ERR_ROLE_RETIRED` otherwise. On a successful launch, the system enrolls every `ACTIVE` grant of an entitlement bundled by the scope role: each such grant moves its review dimension `NOT_DUE` → `UNDER_REVIEW`, and a **certification item** is created for it in `PENDING` decision status. The campaign's `item_count` is set to the number of items created, and its `posture` and `completion_pct` are recomputed.

A certification item is the per-grant line of work. It carries the `campaign_id` of the campaign it belongs to, the `grant_id` of the grant under certification, a `decision_status` that runs `PENDING` → `UNDER_REVIEW` → `CERTIFIED` or `REVOKED`, and a `decided_by_user_id` that stays null until someone decides it. A `Certifier` works the items. Certifying an item keeps the grant: the item moves to `CERTIFIED`, the underlying grant's review dimension bubbles `UNDER_REVIEW` → `CERTIFIED`, the campaign's `completion_pct` is recomputed, and an audit event of type `ITEM_CERTIFIED` is appended. Revoking an item moves it to `REVOKED`, drives the underlying grant's review dimension to `FLAGGED` and cascades the grant's lifecycle from `ACTIVE` to `REVOKED` with the full revoke side effects (which recomputes the affected identity's counters), and recomputes `completion_pct`. Both certify and revoke require the owning campaign to be in `ACTIVE` status; a decision attempted while the campaign is not `ACTIVE` is rejected with `ERR_CAMPAIGN_NOT_ACTIVE`.

Closing a campaign moves it `ACTIVE` → `CLOSED`; it must be `ACTIVE` to close, or the attempt fails with `ERR_INVALID_STATE`. Closing runs the continue-revoke policy: every certification item still in `PENDING` or `UNDER_REVIEW` at close is auto-decided to `REVOKED`, and each such auto-revoked item cascades its grant from `ACTIVE` to `REVOKED` with the full revoke side effects, recomputing each affected identity's counters. After the cascade, `realized_revocation_count` is set to the number of items auto-revoked at close plus the number of items that were explicitly revoked earlier during the campaign, the `posture` becomes `COMPLETE`, and `completion_pct` becomes 100.

### 3.8. Campaign Posture, Completion, and Revocation Impact

The three campaign reporting figures are derived, not stored by a client, and each follows a precise rule. The **posture** is `OPEN` while the campaign is in `DRAFT`; it is `COMPLETE` when every item's `decision_status` is either `CERTIFIED` or `REVOKED` (and likewise `COMPLETE` for a campaign that launched with zero items); otherwise, while at least one item remains undecided, it is `IN_REVIEW`.

The **completion percentage** measures how much of the campaign's work is decided. Let the decided count be the number of items whose `decision_status` is `CERTIFIED` or `REVOKED`, and let the total be the campaign's frozen `item_count` captured at launch. If the total is zero, the completion percentage is 100.00, since an empty campaign is trivially complete. Otherwise the percentage is computed by dividing the decided count by the total in full precision, multiplying that ratio by 100, and rounding the single resulting figure half-up to two decimal places. The division is performed before the rounding — the ratio is taken over the whole campaign and rounded exactly once at the end, never by rounding each item's contribution separately.

The two **revocation-impact** figures are a projected/realized pair. The `projected_revocation_count` is a what-if read available while the campaign is `ACTIVE`: it is the count of items whose `decision_status` is still `PENDING` or `UNDER_REVIEW` — exactly the items that would be auto-revoked if the campaign closed now under the continue-revoke policy. The `realized_revocation_count` is the after-the-fact figure available once the campaign is `CLOSED`: it is the count of items whose `decision_status` is `REVOKED`, which equals the items auto-revoked at close plus any explicitly revoked during the campaign.

### 3.9. Audit Evidence and Orphan Detection

Every consequential action threads through the audit trail. As described in §2.9, grant activation, grant revocation, request approval, request rejection, identity disablement, and item certification each append an immutable audit event recording its `subject_identity_id`, `event_type`, `actor_user_id`, and `detail`. Operator-driven actions stamp the acting operator's `X-User-ID` as `actor_user_id`, while events produced by an automatic cascade are stamped `system`. The `ORPHAN_DETECTED` event type captures the surfacing of an orphan account — a live non-human identity that has fallen to zero active grants — completing the evidence set an auditor needs to reconstruct the access history of any identity. Audit evidence is retrievable both as a global, filterable collection and scoped to a single subject identity.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`; operations that modify, transition, or act upon an existing resource return `200 OK`. Read operations return `200 OK`. The request body, computed side effects, and response shape of each endpoint are governed by the workflows in §3 and are not repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/entitlements` | Create a catalog entitlement | CatalogAdmin |
| GET | `/entitlements/{id}` | Get an entitlement | CatalogAdmin, AccessManager, AccessApprover, CampaignAdmin, Certifier |
| GET | `/entitlements` | List entitlements | CatalogAdmin, AccessManager, AccessApprover, CampaignAdmin, Certifier |
| POST | `/entitlements/{id}/archive` | Archive an entitlement | CatalogAdmin |
| POST | `/roles` | Create a role bundling entitlements | CatalogAdmin |
| GET | `/roles/{id}` | Get a role | CatalogAdmin, AccessManager, AccessApprover, CampaignAdmin, Certifier |
| GET | `/roles` | List roles | CatalogAdmin, AccessManager, AccessApprover, CampaignAdmin, Certifier |
| POST | `/roles/{id}/retire` | Retire a role | CatalogAdmin |
| POST | `/sod-policies` | Create a segregation-of-duties policy | CatalogAdmin |
| GET | `/sod-policies/{id}` | Get a SoD policy | CatalogAdmin, AccessManager, AccessApprover |
| GET | `/sod-policies` | List SoD policies | CatalogAdmin, AccessManager, AccessApprover |
| POST | `/identities` | Create a workforce identity | AccessManager |
| GET | `/identities/{id}` | Get an identity with computed risk and counters | AccessManager, AccessApprover, CampaignAdmin, Certifier |
| GET | `/identities` | List identities; supports orphan-account discovery | AccessManager, AccessApprover, CampaignAdmin, Certifier |
| POST | `/identities/{id}/grants` | Directly provision a grant for an identity | AccessManager |
| POST | `/identities/{id}/disable` | Disable an identity; revoke all active grants | AccessManager |
| POST | `/identities/{id}/enable` | Re-enable a disabled identity | AccessManager |
| POST | `/identities/{id}/deprovision` | Deprovision a disabled identity with zero active grants | AccessManager |
| GET | `/identities/{id}/grants` | List grants held by an identity | AccessManager, AccessApprover, CampaignAdmin, Certifier |
| GET | `/identities/{id}/audit-events` | List audit evidence for an identity | AccessManager, AccessApprover, CampaignAdmin, Certifier |
| POST | `/access-requests` | Raise an access request for an identity and role | AccessManager |
| GET | `/access-requests/{id}` | Get an access request | AccessManager, AccessApprover |
| GET | `/access-requests` | List access requests | AccessManager, AccessApprover |
| POST | `/access-requests/{id}/submit` | Submit a request; evaluate SoD; update projected risk | AccessManager |
| POST | `/access-requests/{id}/return` | Return a submitted request for revision | AccessApprover |
| POST | `/access-requests/{id}/approve` | Approve a request; cascade grant creation and activation | AccessApprover |
| POST | `/access-requests/{id}/reject` | Reject a request | AccessApprover |
| GET | `/grants/{id}` | Get a grant with both state dimensions and risk contribution | AccessManager, AccessApprover, CampaignAdmin, Certifier |
| GET | `/grants` | List grants | AccessManager, AccessApprover, CampaignAdmin, Certifier |
| POST | `/grants/{id}/revoke` | Manually revoke an active grant | AccessManager |
| POST | `/certification-campaigns` | Create a certification campaign scoped to a role | CampaignAdmin |
| GET | `/certification-campaigns/{id}` | Get a campaign with posture, completion, and revocation counts | CampaignAdmin, Certifier, AccessManager |
| GET | `/certification-campaigns` | List campaigns | CampaignAdmin, Certifier, AccessManager |
| POST | `/certification-campaigns/{id}/launch` | Launch a campaign; enroll grants and create items | CampaignAdmin |
| POST | `/certification-campaigns/{id}/close` | Close a campaign; auto-revoke undecided items | CampaignAdmin |
| GET | `/certification-campaigns/{id}/items` | List items of a campaign | CampaignAdmin, Certifier, AccessManager |
| GET | `/certification-items/{id}` | Get a certification item | CampaignAdmin, Certifier, AccessManager |
| GET | `/certification-items` | List certification items | CampaignAdmin, Certifier, AccessManager |
| POST | `/certification-items/{id}/certify` | Certify an item, keeping the grant | Certifier |
| POST | `/certification-items/{id}/revoke` | Revoke an item, cascading grant revocation | Certifier |
| GET | `/audit-events/{id}` | Get a single audit evidence record | AccessManager, AccessApprover, CampaignAdmin, Certifier |
| GET | `/audit-events` | List audit evidence | AccessManager, AccessApprover, CampaignAdmin, Certifier |
| POST | `/_clock/set_current_utc` | Set the server clock for deterministic time-gated tests | CatalogAdmin, AccessManager, CampaignAdmin |

The catalog list and get endpoints accept filters drawn from the workflows above. Entitlement listing accepts `is_privileged` and `status`; role listing accepts `status`; segregation-of-duties policy listing accepts `entitlement_a_id`, `entitlement_b_id`, and `status`. Identity listing accepts `status`, `is_orphan`, and `is_human`. Access-request listing accepts `identity_id`, `role_id`, and `status`. Grant listing accepts `identity_id`, `entitlement_id`, `source_request_id`, `lifecycle_status`, and `review_status`, and the identity-scoped grant listing accepts `lifecycle_status` and `review_status`. Campaign listing accepts `scope_role_id` and `status`. Certification-item listing accepts `grant_id`, `campaign_id`, and `decision_status`, and both the campaign-scoped item listing and the identity-scoped audit listing accept `decision_status` and `event_type` respectively; audit-event listing accepts `subject_identity_id` and `event_type`. All list endpoints additionally accept `limit` and `offset`. The clock-setting capability advances the server's current UTC to the supplied `to_iso8601` instant for deterministic time-gated tests of just-in-time and campaign windows.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_ENUM` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_IDENTITY_NOT_ACTIVE` | 409 Conflict |
| `ERR_ROLE_RETIRED` | 409 Conflict |
| `ERR_ENTITLEMENT_ARCHIVED` | 409 Conflict |
| `ERR_SOD_SELF_ACTION` | 403 Forbidden |
| `ERR_DUAL_APPROVAL_REQUIRED` | 422 Unprocessable Entity |
| `ERR_SOD_CONFLICT` | 409 Conflict |
| `ERR_SOD_OVERRIDE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_JIT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CAMPAIGN_NOT_ACTIVE` | 409 Conflict |
| `ERR_CAMPAIGN_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_IDENTITY_HAS_ACTIVE_GRANTS` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SOD_PAIR_INVALID` | 422 Unprocessable Entity |

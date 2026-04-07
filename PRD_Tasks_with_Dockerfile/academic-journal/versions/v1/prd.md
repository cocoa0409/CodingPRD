# Academic Journal Peer-Review System - Product Requirements Document

## 1. Academic Journal Peer-Review System

This document outlines the requirements for the Academic Journal Peer-Review System API, a platform designed to manage the complete lifecycle of scholarly manuscript evaluation. It provides the necessary facilities for establishing academic journals, submitting manuscripts for review, managing the intricate process of peer evaluation, and maintaining the delicate balance between academic rigor and journal reputation through a sophisticated system of prestige management and risk assessment.

## 2. Global Specifications

### 2.1 Authentication & User Context

User context is determined by two mandatory HTTP request headers for all endpoints:

*   `X-User-ID`: (string) The unique identifier of the user making the request. This ID is used for authorization checks and data association.
*   `X-User-Role`: (string) The role assigned to the user. Must be one of the following values: `JournalEditor`, `SectionEditor`, `ManagingEditor`.

Failure to provide these headers will result in a `400 Bad Request` with `error_id: ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.

While endpoint access is open, actions are restricted by user role. If a user attempts to perform an action not permitted for their role (e.g., a `SectionEditor` attempting to finalize publication), the API will respond with a `403 Forbidden` error with an `error_id` of `ERR_INSUFFICIENT_PERMISSIONS`.

### 2.2 Standard API Response Formats

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "object" | "array",
  "data": {}
}
```

*   The `api_request_id` is a server-generated unique identifier for the request, designed to facilitate logging and traceability, that begins with the prefix 'req_' followed by alphanumeric characters.
*   The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
*   The `response_type` is either "object" for a single resource or "array" for a list of resources.
*   The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object.

In adherence to data consistency principles, unique identifiers such as journal IDs are formatted as UUIDs.

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

*   The `error_id` is a unique, machine-readable string that identifies the specific error.
*   The `message` provides a human-readable explanation of what went wrong.

### 2.3 Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. In our approach to balancing comprehensive data delivery with performance considerations, clients can specify a `limit` parameter, an integer that, when not provided, defaults to a value of 10, with allowable ranges bounded between a minimum of 1 and a maximum of 100 to prevent overload. The number of initial items to skip is controlled by the `offset` parameter, an integer that, to support sequential data retrieval without gaps, defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4 Data Scoping & Isolation

All data within the system is scoped to a single, top-level **Journal**. This is the primary container for all other resources, including manuscripts, review assignments, reviewer profiles, and conflicts of interest. All operations and data visibility are strictly isolated within the context of a given Journal, ensuring that one publication cannot access or interfere with the resources of another.

### 2.5 Core Systems

The platform operates on two fundamental background systems that track the state of a Journal.

*   **Prestige Budget Ledger**: This reputation management tool tracks the academic standing of a Journal. It maintains two separate cost fields: `provisional_costs` for reviews currently in progress and `finalized_costs` for completed and published reviews. The journal's remaining prestige is calculated as `total_prestige - provisional_costs - finalized_costs`. Any ledger decrement operations follow the integrity principles to prevent negative values. For context, the editorial board observes that a reviewer can comfortably juggle no more than five simultaneous assignments – a figure that indirectly informs our acceptable revision bandwidth.
*   **Desk Reject Risk Ledger**: This accountability ledger tracks the quality of submissions associated with a Journal. It maintains a `risk_score` field that reflects the journal's history of low-quality submissions. Unlike traditional health metrics that start high and decrease, this risk metric starts low and increases with problematic patterns. Any mutation (increment, decrement, or update) to `PrestigeBudgetLedger` or `DeskRejectRiskLedger` automatically updates the `prestige_balance` and `desk_reject_risk_score` fields on the corresponding Journal.

In the framework of academic governance, the maximum tolerable threshold for a journal's risk score before submission restrictions are enforced is established at 100 points.
Upon the establishment of a new journal, to provide a clean slate for its reputation management, the risk score in the Desk Reject Risk Ledger is initialized to a value of 0.
In line with prestige preservation policies, the prestige balance cannot fall below 0 and is capped at the initial total prestige allocation.
Cancellation policies ensure reversal of any prestige or risk ledger entries affected by the review.

### 2.6 System Invariants

The following system-wide rules and constraints apply to all operations within the Academic Journal Peer-Review System.

*   **Manuscript Revision Quota**: To encourage high-quality initial submissions and prevent excessive revision cycles, each manuscript is allotted a standard number of review assignments before it begins to significantly impact the journal's reputation. Assignments beyond this standard allotment are deemed extra-revision cycles and incur reputational penalties.
*   **Revision Penalty Multiplier**: Reviews that are part of an extra revision cycle incur a greater cost to the journal's prestige. In alignment with our policy to incentivize efficient and thorough peer review from the outset, the prestige cost for such reviews is calculated using a multiplier, set to a value of 1.5, on the standard base cost of a review.
*   **Reviewer Concurrency Limit**: To ensure that reviewers can provide thoughtful and timely feedback without becoming overwhelmed, the system limits the number of active reviews a single reviewer can have at one time. A reviewer is not eligible to be invited to a new review if their number of active reviews (those in `INVITED` or `ACCEPTED` status) has reached the maximum capacity. To maintain this standard of quality while allowing productive reviewers to contribute meaningfully, the system imposes a limit of 5 concurrent reviews per reviewer. An attempt to invite an overloaded reviewer will be rejected.
*   **Journal Risk Threshold**: A Journal's risk score is a critical indicator of its submission quality and editorial standards. When inviting a reviewer to an assignment that is part of an extra revision cycle, the system evaluates whether the journal's risk score would meet or exceed the submission lock threshold after applying the extra revision penalty. If this projected score would breach the threshold defined under Academic Governance principles, the system rejects the invitation. This restriction cannot be bypassed, and attempting to invite a reviewer under these conditions will result in a `403 Forbidden` response with an `ERR_RISK_THRESHOLD_BREACHED` error.
*   **Risk Penalty for Extra Revisions**: Utilizing extra revision cycles, while sometimes necessary for complex manuscripts, indicates potential issues with either the initial submission quality or the review process efficiency. As such, each time a Review invitation is created for an assignment that exceeds the standard revision quota, a penalty is assessed against the journal's risk score to reflect this concern. In line with our goal to discourage excessive revision cycles that can delay publication and consume reviewer resources, a value of 20 points is added to the journal's risk score for each such occurrence.
*   **Risk Penalty for Fast-Tracking**: Requesting an expedited review process for a manuscript signals urgency but also introduces a higher risk of oversight and reduced review quality. To account for this trade-off, when a `SectionEditor` marks a manuscript for fast-track submission during creation, an immediate penalty is assessed against the journal's risk score. This upfront risk assessment, designed to discourage overuse of expedited processes, carries a penalty of 5 points.
*   **Prestige Cost for Submission**: The act of formally submitting a manuscript into the peer-review system represents an initial investment of the journal's resources and reputation. As such, when a manuscript's status is advanced to signify it is ready for review, a standard, non-refundable cost is deducted from the journal's prestige budget. This initial investment, which reflects the administrative and reputational commitment to the review process, is valued at ten times the cost of a standard review invitation.

Lifecycle governance restricts the beginning of review cycles to journals solely in the ACCEPTING_SUBMISSIONS state.

To uphold the highest standards of impartiality in peer review, the system's default review process is `DOUBLE_BLIND`, masking the identities of both author and reviewer unless a different `required_anonymity_level` is explicitly requested for an assignment.

## 3. Business Logic & Workflows

### 3.1 The Journal Lifecycle

The foundational resource in the system is the **Journal**. It represents a complete academic publication and serves as the container for all other resources. A new journal is initiated by a `JournalEditor` with a `journal_name` and a `total_prestige`. Upon creation, the system automatically generates a unique `id` according to the identifier standards and timestamps for `created_at` and `updated_at`. As journals begin their lifecycle in a phase where submissions are welcomed, their status reflects this open state. The journal's reputational standing is tracked via a read-only prestige indicator, and its submission quality is monitored by a read-only risk-profile score, both of which are derived from their respective ledgers.

A journal must be transitioned from its initial state to `IN_REVIEW` before any reviews can be formally managed. This is a deliberate action by a `JournalEditor` signifying that the editorial board is ready to begin the review process. An attempt to begin review for a journal not in the appropriate state will result in a `409 Conflict` error with `ERR_JOURNAL_LIFECYCLE_STATE_INVALID`. Any attempt to invite reviewers while the journal is not `IN_REVIEW` will result in a `409 Conflict` with the error `ERR_JOURNAL_NOT_IN_REVIEW`. Once a journal is `IN_REVIEW`, `SectionEditors` can begin inviting reviewers for assignments.

When all manuscripts have been evaluated and all reviews have been finalized (i.e., are not in an invited or accepted state), the journal can be moved by a `JournalEditor` to `PUBLICATION_PENDING`. An attempt to do so when unresolved reviews exist will result in a `409 Conflict` with `ERR_UNRESOLVED_REVIEWS_EXIST`. This state transition prepares the journal for final publication processing. The final lifecycle step, managed by a `ManagingEditor`, is to finalize publication, which moves the journal to its terminal `ARCHIVED` state.
Upon the commencement of a new journal, its ledgers are initialized to reflect a clean slate, with no prior costs or risk penalties having been incurred.

### 3.2 Manuscript Submission and Review Assignment Creation

When a `SectionEditor` submits a new **Manuscript** to a journal, they provide a `title` and a `submission_date`, represented as a Unix timestamp denoting seconds since the epoch. The manuscript is created with a reference to its parent `journal_id`. Manuscripts can only be created when the journal is in the `ACCEPTING_SUBMISSIONS` state; attempting to create a manuscript when the journal is in any other state will result in a `409 Conflict` error (`ERR_JOURNAL_NOT_ACCEPTING_SUBMISSIONS`). Additionally, if a `SectionEditor` attempts to submit a manuscript to a journal whose risk score, as tracked by the accountability mechanisms, has reached the submission lock threshold, the request will be denied with a `403 Forbidden` error (`ERR_RISK_SCORE_TOO_HIGH`).

The manuscript's `status` begins in `DRAFT`. This initial state allows for the creation of review assignments before formal submission. A manuscript cannot proceed to peer review without defined review assignments, ensuring proper preparation. Once review assignments are created, the manuscript can be transitioned to `PENDING_REVIEW`. This state transition, which can only be performed by a `JournalEditor`, triggers the initial prestige cost deduction. An attempt to transition a manuscript to `PENDING_REVIEW` when no review assignments have been created will be denied with a `409 Conflict` error (`ERR_NO_ASSIGNMENTS`), enforcing the requirement for proper review preparation. An attempt to create review assignments for a manuscript while its parent journal is not `IN_REVIEW` will result in a `409 Conflict` with the error `ERR_JOURNAL_NOT_IN_REVIEW`.

Within each Manuscript, the peer-review process is structured through **Review Assignments**. A `SectionEditor` creates these assignments, which represent discrete units of evaluation needed for the manuscript. Each assignment is created with a `required_expertise` to guide the selection of a suitable reviewer, reflecting the specific domain knowledge needed for that aspect of the manuscript. The assignment may specify a `required_anonymity_level`, which must be one of `SINGLE_BLIND`, `DOUBLE_BLIND`, or `OPEN_PEER_REVIEW`. If no anonymity level is specified, the system defaults to the most rigorous standard to ensure impartiality. Each assignment also includes a `due_date`, represented as a Unix timestamp, establishing the timeline for review completion. The assignment maintains references to its parent `manuscript_id` and `journal_id`. For organizational and policy enforcement purposes, the system automatically calculates a read-only `revision_cycle` field for every assignment, derived from the total number of assignments created for the manuscript. The board considers the initial scholarly assessment to be complete after a trio of expert opinions have been gathered. A `ReviewAssignment`'s status begins as `PENDING_ASSIGNMENT`.

Once a manuscript is in the `PENDING_REVIEW` state, it can follow several paths. It may be moved to `IN_REVISION` if the reviewers recommend substantial changes, or to the terminal states of `ACCEPTED` or `REJECTED` based on the review outcomes. A manuscript can also be directly rejected from the `DRAFT` state through a desk rejection process, transitioning immediately to the `REJECTED` terminal state. Manuscripts that require revision can cycle back from `IN_REVISION` to `PENDING_REVIEW` after authors address reviewer concerns, creating additional review cycles that impact the journal's risk profile.

When a manuscript transitions to the `REJECTED` state, the system ensures comprehensive cleanup of associated review processes and reverses any speculative risk assessments. For manuscripts that were marked for expedited processing, the risk penalty assessed at creation time reflects a concern that ultimately did not materialize into actual review work, and thus this penalty is reversed upon rejection. This transition triggers automatic cancellation of all reviews that have not yet reached their terminal states, specifically those in `INVITED`, `ACCEPTED`, or `SUBMITTED` status, moving them to the `CANCELLED` state. This cascading cancellation mirrors the individual review cancellation process, restoring any provisionally debited prestige costs to the journal's balance and reversing any risk penalties that were assessed when these reviews were initiated. The manuscript's rejection thus cleanly unwinds all uncommitted review activities and speculative risk assessments, ensuring the journal's ledgers accurately reflect only completed academic work and realized risks.

### 3.3 The Review Invitation Process

The critical link between an assignment and an academic peer is the **Review**. A review represents an invitation, initiated by a `SectionEditor`, to assign a specific Review Assignment to a qualified **Reviewer Profile**. The system maintains profiles for academics who serve as reviewers, each defined by their `full_name` and the `institution` they are affiliated with. Each profile maintains a reference to its parent `journal_id` and can have one or more `certifications` applied to it by a `SectionEditor`. These certifications are structured as a list where each certification has a unique `id`, a `name` which must be one of the enumerated values (`PhD`, `MD`, or `JD`), and a `granted_date`, providing verification of the reviewer's qualifications.

Creating a review invitation is a multi-step process governed by a strict validation sequence designed to ensure quality, fairness, and system integrity. First, an invitation is proposed, but only if the assignment is in the `PENDING_ASSIGNMENT` state; any attempt to invite a reviewer for an assignment not in this state will be rejected with a `409 Conflict` (`ERR_ASSIGNMENT_NOT_PENDING`). The parent journal must also be in the `IN_REVIEW` state, or the invitation will be rejected with `ERR_JOURNAL_NOT_IN_REVIEW`.

The system's responsibility is to ensure reviewer suitability and availability. It validates that the selected Reviewer Profile's list of `expertise_areas` contains the assignment's `required_expertise`. A mismatch between reviewer expertise and assignment requirements results in a `400 Bad Request` (`ERR_EXPERTISE_MISMATCH`). The system also enforces the **Reviewer Concurrency Limit** to prevent overloading any single academic.

With expertise and workload constraints satisfied, the system then assesses ethical and academic integrity rules. To maintain the impartiality essential to peer review, it verifies that the invitation would not violate any registered **Conflicts of Interest**. The system examines the complete conflict registry for any relationships that would compromise the review process. For institutional conflicts, it verifies whether the prospective reviewer has been marked as having an institutional affiliation conflict within the journal's records. The evaluation extends beyond simple institutional checks to encompass professional collaboration histories. Any reviewer who has been identified in the conflict registry as having prior collaborative relationships must be excluded from review opportunities where such relationships exist. When either form of conflict is detected—whether through the `INSTITUTIONAL` or `PRIOR_COLLABORATION` designation in the registry—the invitation process halts with a `409 Conflict` response, accompanied by the appropriate error identifier to ensure transparency about the specific impediment.

Following these integrity checks, and in line with the validation hierarchy principles that prioritize safeguarding the journal's long-term submission quality over immediate resource allocation, the focus shifts to reputational and financial viability. The system evaluates whether the assignment belongs to an extra revision cycle by checking if the manuscript's total assignments exceed the quota. If the invitation is for an extra revision cycle assignment, the system calculates the projected risk score impact. If this would breach the **Journal Risk Threshold**, the invitation is rejected with a `403 Forbidden` error (`ERR_RISK_THRESHOLD_BREACHED`). Finally, once all other checks have passed, the system validates the reputational impact. It calculates the `provisional_prestige_cost` for the review, a figure that begins with the administrative effort of issuing an invitation valued at 1 prestige point and is then adjusted by any applicable revision penalty multiplier. If this cost exceeds the journal's available prestige balance, the proposal is rejected with a `402 Payment Required` error (`ERR_INSUFFICIENT_PRESTIGE`).

Upon successful invitation, a Review is created with a status of `INVITED`, and the associated Review Assignment is moved to `INVITED` as well. The system records whether the review `in_extra_revision_cycle` based on the assignment's position relative to the manuscript revision quota. The calculated `provisional_prestige_cost` is provisionally debited from the journal's `prestige_balance`. If the review is determined to be part of an extra revision cycle, the associated risk penalty is immediately applied to the journal's risk score, reflecting the concern about extended revision processes.

### 3.4 Managing Academic Integrity: Conflicts of Interest

To prevent bias and maintain the credibility of the peer-review process, `JournalEditors` can register a **Conflict of Interest**. This resource creates a formal record of relationships or circumstances that would compromise the impartiality of a review. Each conflict record contains references to the two entities involved, designated as `entity_1_id` and `entity_2_id`, which typically represent reviewer profiles but may also represent institutions or other entities depending on the conflict type. The record includes a reference to the parent `journal_id` and a mandatory `conflict_type` field which must be one of `INSTITUTIONAL` or `PRIOR_COLLABORATION`, categorizing the nature of the conflict for proper handling during reviewer selection. An optional free-text `reason` field may be included to document the specific circumstances of the conflict for administrative purposes.

To prevent logical errors in conflict management, the system validates that a conflict cannot be created where both entities are identical. Such an attempt, which would represent a reviewer conflicted with themselves, results in a `400 Bad Request` (`ERR_SELF_CONFLICT`). The conflict registry is consulted during every review invitation, ensuring that these integrity constraints are actively enforced throughout the review process.

### 3.5 Review Lifecycle and State Management

An invited review follows a carefully managed lifecycle designed to ensure accountability and proper tracking. From the initial `INVITED` state, a review can transition along several paths. It may be accepted by a `JournalEditor`, moving to the `ACCEPTED` state and indicating the reviewer's commitment to complete the evaluation. Alternatively, it can be declined, transitioning to the terminal `DECLINED` state and automatically reverting the associated assignment to `PENDING_ASSIGNMENT` to allow for a new reviewer selection. This declination also reverses any provisional prestige costs debited from the journal's budget and restores any risk penalties that were applied when the invitation was created.

An accepted review represents a commitment from the reviewer and updates the assignment status to `ASSIGNED`. The reviewer then prepares their evaluation, and when complete, a `JournalEditor` can submit the review, transitioning it to the `SUBMITTED` state. This submission represents the completion of the reviewer's obligations but not yet the formal publication of their feedback.

Reviews can be cancelled by a `JournalEditor` from the `INVITED`, `ACCEPTED`, or `SUBMITTED` states, which transitions them to the terminal `CANCELLED` state. This cancellation reverts the associated assignment to `PENDING_ASSIGNMENT` and reverses all financial and risk impacts, including the restoration of provisionally debited prestige costs and the reversal of any risk penalties that were assessed. The ability to cancel even submitted reviews provides flexibility for handling exceptional circumstances while maintaining system integrity.

The final state transition occurs during the journal publication process. When a `ManagingEditor` finalizes publication, all reviews in the `SUBMITTED` state are transitioned to the terminal `PUBLISHED` state, making them part of the permanent academic record. To ensure process integrity, terminal states such as `PUBLISHED` for completed reviews, `DECLINED` for refused invitations, and `CANCELLED` for aborted reviews cannot transition further, maintaining an immutable audit trail of the peer-review process.

Assignment states follow a parallel lifecycle. From `PENDING_ASSIGNMENT`, they move to `INVITED` when a reviewer is invited, then to `ASSIGNED` when the invitation is accepted. They can also transition to the terminal `CANCELLED` state if explicitly cancelled by a `SectionEditor`. This cancellation is only permitted when the assignment is in the `PENDING_ASSIGNMENT` state, preventing disruption of active reviews. An attempt to cancel an assignment in any other state results in a `409 Conflict` (`ERR_ASSIGNMENT_NOT_PENDING_FOR_CANCEL`).

### 3.6 Risk Management and Quality Control

The risk-profile score of a Journal is a key metric for maintaining submission quality standards. Unlike traditional health metrics that start at an optimal value and decrease, this risk score starts at 0 and increases with problematic patterns, providing an intuitive measure where higher values indicate greater concern.

The most significant control mechanism is the submission lock threshold. When a journal's risk score reaches or exceeds the lock value of 100 points, the system prevents new manuscript submissions to allow the editorial team to address quality concerns. This lock cannot be overridden, ensuring that journals must actively manage their submission quality to continue operations. The risk score increases through several mechanisms. The accountability mechanisms are sensitive to procedural shortcuts. For instance, requests for expedited review, made via the `is_fast_track_submission` flag on a manuscript, are discouraged through a subtle but immediate 5-point addition to the journal's risk score. Reviews in extra revision cycles add 20 points each, reflecting the compound concern of both extended review processes and the resources they consume, particularly when more than the customary three initial assessments are required.

As a foundational aspect of quality management, the risk score begins at 0 upon journal creation, providing a clean baseline from which deviations are measured. This accumulating metric serves as an early warning system, encouraging editorial teams to maintain high standards before reaching critical thresholds.

### 3.7 Publication and Finalization

The culmination of a Journal's review cycle is the generation of a final publication record. This action can only be performed when the journal is in the `PUBLICATION_PENDING` state. Any attempt to finalize publication for a journal not in this state will result in an error. The system performs a comprehensive finalization of all Reviews in the `SUBMITTED` state, transitioning them to `PUBLISHED` and calculating their `final_prestige_cost`.

This final calculation may differ from the provisional cost if circumstances changed during the review process. The system moves these final costs from the provisional costs to the finalized costs on the Prestige Budget Ledger, providing an accurate accounting of the journal's reputational investment. Upon successful completion, the journal itself is transitioned to the `ARCHIVED` state, creating a permanent record of the publication cycle. This archival process ensures that all reviews are properly preserved and that the journal's final prestige balance, which begins with no provisional or finalized costs, accurately reflects the total cost of the peer-review process.

## 4. Endpoint Definitions

All successful creation operations return 201 Created, while other successful operations return 200 OK.

### 4.1 Journal Management Endpoints

*   **POST /journals**: Create a new Journal.
*   **GET /journals**: List all Journals.
*   **GET /journals/{journalId}**: Get a specific Journal.
*   **POST /journals/{journalId}/begin-review**: Move a journal to the `IN_REVIEW` state, enabling the review process.
*   **POST /journals/{journalId}/initiate-publication**: Move a journal to the `PUBLICATION_PENDING` state.
*   **POST /journals/{journalId}/finalize-publication**: Finalize prestige costs, publish reviews, and archive the journal.

### 4.2 Manuscript and Assignment Endpoints

*   **POST /journals/{journalId}/manuscripts**: Create a new Manuscript within a Journal.
*   **GET /journals/{journalId}/manuscripts**: List Manuscripts for a Journal.
*   **GET /journals/{journalId}/manuscripts/{manuscriptId}**: Get a specific Manuscript.
*   **PUT /journals/{journalId}/manuscripts/{manuscriptId}**: Update a Manuscript's status.
*   **POST /journals/{journalId}/manuscripts/{manuscriptId}/review-assignments**: Create a new Review Assignment for a Manuscript.
*   **GET /journals/{journalId}/manuscripts/{manuscriptId}/review-assignments**: List Review Assignments for a Manuscript.
*   **GET /journals/{journalId}/manuscripts/{manuscriptId}/review-assignments/{assignmentId}**: Get a specific Review Assignment.
*   **POST /journals/{journalId}/manuscripts/{manuscriptId}/review-assignments/{assignmentId}/cancel**: Cancel a specific Review Assignment.

### 4.3 Reviewer Profile Endpoints

*   **POST /journals/{journalId}/reviewer-profiles**: Create a new Reviewer Profile for a Journal.
*   **GET /journals/{journalId}/reviewer-profiles**: List Reviewer Profiles for a Journal.
*   **GET /journals/{journalId}/reviewer-profiles/{reviewerId}**: Get a specific Reviewer Profile.
*   **POST /journals/{journalId}/reviewer-profiles/{reviewerId}/certifications**: Add a certification to a Reviewer Profile.

### 4.4 Review Management Endpoints

*   **POST /journals/{journalId}/reviews**: Invite a Reviewer for a Review Assignment.
*   **GET /journals/{journalId}/reviews**: List all Reviews for a Journal.
*   **GET /journals/{journalId}/reviews/{reviewId}**: Get a specific Review.
*   **POST /journals/{journalId}/reviews/{reviewId}/accept**: Accept an invited Review.
*   **POST /journals/{journalId}/reviews/{reviewId}/submit**: Submit an accepted Review.
*   **POST /journals/{journalId}/reviews/{reviewId}/decline**: Decline an invited Review. When declining a review, the system first verifies the review exists. If the provided reviewId does not correspond to a valid review, the system returns a 404 Not Found with error_id ERR_REVIEW_NOT_FOUND.
*   **POST /journals/{journalId}/reviews/{reviewId}/cancel**: Cancel a Review.
In managing review lifecycles, acceptance is restricted by the `JournalEditor` to reviews in the INVITED state. An attempt to accept a review not in the 'INVITED' state will result in a 409 Conflict with error_id: ERR_REVIEW_LIFECYCLE_STATE_INVALID. Similarly, declining a review is only possible when the review is in the `INVITED` state. Attempting to decline a review in any other state will result in a `409 Conflict` with the same `ERR_REVIEW_LIFECYCLE_STATE_INVALID` error. Submitting a review is only permitted when the review is in the `ACCEPTED` state, and an attempt to submit from any other state will also result in a `409 Conflict` with `ERR_REVIEW_LIFECYCLE_STATE_INVALID`.

### 4.5 Conflict of Interest Endpoints

*   **POST /journals/{journalId}/conflicts-of-interest**: Create a Conflict of Interest within a Journal.
*   **GET /journals/{journalId}/conflicts-of-interest**: List Conflicts of Interest for a Journal.
*   **GET /journals/{journalId}/conflicts-of-interest/{conflictId}**: Get a specific Conflict of Interest.
In managing conflicts of interest, a key rule is that an entity cannot be in conflict with itself to avoid illogical configurations.

## 5. Error Code Catalogue

| Error ID                            | HTTP Status Code     |
| :---------------------------------- | :------------------- |
| `ERR_JOURNAL_NOT_FOUND`             | 404 Not Found        |
| `ERR_REVIEWER_NOT_FOUND`            | 404 Not Found        |
| `ERR_SELF_CONFLICT`                 | 400 Bad Request      |
| `ERR_ASSIGNMENT_NOT_FOUND`          | 404 Not Found        |
| `ERR_ASSIGNMENT_NOT_PENDING_FOR_CANCEL` | 409 Conflict     |
| `ERR_JOURNAL_NOT_ACCEPTING_SUBMISSIONS` | 409 Conflict     |
| `ERR_RISK_SCORE_TOO_HIGH`           | 403 Forbidden        |
| `ERR_MANUSCRIPT_NOT_FOUND`          | 404 Not Found        |
| `ERR_JOURNAL_NOT_IN_REVIEW`         | 409 Conflict         |
| `ERR_ASSIGNMENT_NOT_PENDING`        | 409 Conflict         |
| `ERR_EXPERTISE_MISMATCH`            | 400 Bad Request      |
| `ERR_REVIEWER_OVERLOADED`           | 409 Conflict         |
| `ERR_INSTITUTIONAL_CONFLICT`        | 409 Conflict         |
| `ERR_PRIOR_COLLABORATION`           | 409 Conflict         |
| `ERR_RISK_THRESHOLD_BREACHED`       | 403 Forbidden        |
| `ERR_INSUFFICIENT_PRESTIGE`         | 402 Payment Required |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS`      | 403 Forbidden        |
| `ERR_JOURNAL_NOT_PENDING_PUBLICATION` | 409 Conflict         |
| `ERR_MANUSCRIPT_LIFECYCLE_STATE_INVALID` | 409 Conflict       |
| `ERR_REVIEW_LIFECYCLE_STATE_INVALID`    | 409 Conflict         |
| `ERR_JOURNAL_LIFECYCLE_STATE_INVALID` | 409 Conflict         |
| `ERR_UNRESOLVED_REVIEWS_EXIST`      | 409 Conflict         |
| `ERR_REVIEW_NOT_FOUND`              | 404 Not Found        |
| `ERR_NO_ASSIGNMENTS`                | 409 Conflict         |
| `ERR_INVALID_PAGINATION_PARAMETERS` | 400 Bad Request      |
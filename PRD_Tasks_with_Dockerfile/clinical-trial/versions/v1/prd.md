# Clinical Trial Governance Platform
## Product Requirements Document

**Domain:** Clinical Research Operations, Ethical Compliance, and Risk Management  
**Target Users:** Research Directors, Clinical Coordinators, Ethics Auditors

---

## 1. Introduction & Vision

### 1.1 Purpose

The Clinical Trial Governance Platform provides comprehensive oversight and management capabilities for multi-trial research programs. The platform addresses the complex interplay between investigator accountability, patient safety, ethical compliance budgeting, and portfolio-level risk containment.

In modern clinical research, individual trials do not operate in isolation. A single investigator's reputation affects their spending authority across all active trials. A safety incident in one trial can ripple through an entire portfolio. Procedural deviations from approved protocols require ethical review resources that must be carefully allocated. This platform models these real-world dependencies to enable responsible, scalable research governance.

### 1.2 Core Entities

The platform organizes all clinical research activities within Research Programs—container resources that provide deterministic sequencing, resource scoping, and temporal coordination. Each program maintains an internal clock based on discrete period indices rather than wall-clock time, ensuring reproducible auditing and simulation capabilities.

Key entities within a program include:

Clinical Trials: Investigations of specific treatments, each associated with a single investigator

Trial Portfolios: Groupings of related trials that share ethical budget caps and risk exposure

Investigators: Research professionals whose trust score governs their spending authority

Trial Phases: Sequential stages (Phase I through IV) within each trial

Protocol Procedures: Specific tests or interventions defined by the trial protocol

Patient Cohorts: Study populations with specific characteristics and risk profiles

Procedure Executions: Actual or proposed implementations of protocol procedures on cohorts

Institutional Review Boards (IRBs): Oversight bodies that approve trial protocols

### 1.3 Business Context

Research institutions face mounting pressure to demonstrate both scientific rigor and ethical stewardship. Regulatory bodies require clear audit trails. Funding agencies demand efficient use of resources. Patient advocacy groups insist on safety accountability.

This platform responds to these pressures by:

Tying investigator privileges to performance: Researchers who demonstrate poor safety records or abandon trials face tighter budget constraints and reduced autonomy

Enabling portfolio-level risk management: Directors can group related trials and prevent over-concentration of ethical exposure

Providing deterministic governance: All temporal logic uses integer period indices, enabling exact replay and what-if analysis

Enforcing protocol discipline: Deviations from approved procedures consume ethical review capacity and trigger escalating scrutiny

---

## 2. System Principles & Foundational Concepts

### 2.1 Deterministic Time and Program Periods

Unlike traditional systems that rely on wall-clock timestamps, the platform uses an explicit program clock represented by `current_period_index`—a non-negative integer that advances only through deliberate administrative action.

This design enables several critical capabilities:

Audit Reproducibility: Reviewers can replay historical states exactly

Scenario Planning: Directors can simulate future periods without affecting production data

Enrollment Control: Blackout windows are defined over period ranges, not brittle date ranges

The program clock begins at period 0 and can be advanced by 1 to 10,000 periods per request. All temporal business rules (enrollment blackouts, cohort certifications) reference these integer indices.

### 2.2 Resource Versioning and Optimistic Concurrency

Every mutable resource and ledger carries a `version` number that increments with each successful mutation. This enables safe concurrent operations in a distributed environment.

The first to commit wins

Subsequent operations receive `409 ERR_VERSION_MISMATCH`

Clients retry with updated state

This approach ensures that ledger operations (budget debits, risk accumulations) maintain arithmetic correctness even under heavy concurrent load, preventing over-commitment of scarce resources.

### 2.3 Ledger Integrity and Balance Reconciliation

The platform maintains several ledger systems that track scarce resources:

1. Ethical Compliance Budget Ledger (per trial): Tracks provisional and finalized ethical review costs

2. Patient Safety Risk Ledger (per trial): Accumulates risk exposure points

3. Investigator Reputation Ledger (per program-investigator pair): Records trust scores

A fundamental principle: ledgers never go negative. All debit operations are validated against available balance before commitment. If concurrent operations would cause overdraft, the system rejects one or more to maintain non-negative balances.

The platform maintains real-time visibility into each trial's spending capacity. This available balance reflects the trial's current spending authority, reduced by both funds already committed to pending activities and funds irrevocably consumed by completed work. The accounting ensures that no new commitment can proceed if it would exhaust the trial's fiscal capacity.

Ledger changes propagate immediately to derived fields visible on resource representations. There is no eventual consistency—when you read a trial's `ethical_compliance_balance`, it reflects all committed operations in that response.

### 2.4 Derived Fields and Synchronization Guarantees

Several resource fields are computed from underlying ledgers rather than stored directly:

A trial's `patient_safety_risk` reflects its safety ledger

A trial's `ethical_compliance_balance` derives from its effective budget minus both provisional and finalized debits

A portfolio's `is_risk_saturated` flag computes from member trials' aggregate consumption

Derived fields reflect the current ledger state in API responses—there are no intermediate states visible to clients. If a deviation proposal adds 50 points of provisional debit, the response will show the trial's balance reduced by exactly 50 points.

### 2.5 Container Scoping and Isolation

Research Programs act as strong boundaries. Resources reference other resources only within the same program (with rare exceptions explicitly noted). Every trial and its child resources (phases, procedures, executions) carry a `research_program_id` field that ties them back to their originating container, ensuring all operations stay within the intended scope.

When creating resources, the platform assigns a `created_seq` value—a monotonically increasing integer scoped to the container. All list endpoints return resources ordered by their `created_seq` in ascending order, providing deterministic, stable sorting.

### 2.6 State Management Philosophy

Resources follow well-defined lifecycle states. State transitions occur as side effects of business operations:

Activating a trial checks prerequisites (completed dependencies, approved IRB) and then transitions from `DRAFT` to `ACTIVE`

Marking an execution as passed transitions both the execution (to `PASSED`) and its parent procedure (to `PASSED`) simultaneously

Some state transitions cascade. When a trial's safety risk crosses a critical threshold during `ACTIVE` status, the system automatically transitions the trial to `ETHICAL_REVIEW_LOCK` and initiates investigator penalties and portfolio contagion.

---

## 3. Investigator Trust & Accountability

### 3.1 Reputation as a Trust Index

Each investigator within a program maintains a `reputation_score` ranging from 0 to 100, initialized at 100. This score represents the institution's confidence in the investigator's judgment and serves as a multiplier for spending authority.

Investigator reputation ledgers initialize either through an explicit initialization endpoint (always safe to call; idempotent if already initialized) or implicitly on the first operation that references that program-investigator pair. Read operations (like listing trials) never create ledger side effects. The first mutation (such as creating a trial for that investigator) triggers initialization with the default 100-point score.

Reputation changes occur due to several events:

Ethical Review Lock: When one of an investigator's trials enters `ETHICAL_REVIEW_LOCK` status due to excessive safety risk, their reputation suffers an immediate penalty

Trial Abandonment: Abandoning a trial (whether from `DRAFT` or `ACTIVE`) reduces reputation by 10 points

Dependency Ripple: Completing a high-risk trial (final safety risk above 75) penalizes each investigator whose trial depended on the completed trial, reducing their reputation by 5 points

Reputation increases must be handled through external processes (not covered by this platform).

### 3.2 Probation Status and Constraints

Investigators whose reputation falls below acceptable levels for autonomous operation enter probationary status. Probation imposes two restrictions:

New trials cannot be created with `total_ethical_compliance_budget` exceeding 500 points

The investigator cannot propose any protocol deviation, regardless of available budget

The platform computes probation status automatically based on the reputation score—a derived boolean reflecting whether trust has fallen below acceptable levels.

Probation affects operational privileges immediately. When an investigator's reputation falls below the institutional confidence threshold, probationary restrictions activate instantly—even a single-point drop can trigger the transition if it crosses this critical boundary.

During probation, trial creation requests are subject to heightened scrutiny. The institution limits the scale of new commitments that can be initiated under reduced confidence levels. This cap on nominal trial budgets—set at five hundred points—prevents circumventing probationary oversight through multiple smaller trials while still permitting continued research activity at reduced scope. The probationary threshold itself is calibrated to forty points, balancing oversight needs with research continuity. During probation, the investigator cannot propose any protocol deviation, regardless of available budget.

### 3.3 Effective Budget Calculation and Propagation

An investigator's reputation directly scales their spending authority. Each trial's actual spending limit reflects the institution's current confidence level in that investigator—higher confidence translates to proportionally greater budgetary autonomy, while reduced trust tightens fiscal controls accordingly.

Reputation changes have immediate operational consequences. When the institution adjusts an investigator's trust score—whether due to ethical violations, trial abandonments, or dependency ripples—the investigator's spending authority updates instantly across their entire research portfolio. Active trials under their management immediately reflect the new confidence level, with their operational budgets scaling accordingly. This ensures that fiscal controls remain synchronized with institutional oversight in real-time.

---

## 4. Clinical Trial Lifecycle

### 4.1 Trial Creation and Portfolio Assignment

Clinical trials begin in `DRAFT` status. Creation requires:

A `treatment_name` describing the intervention under study

A `total_ethical_compliance_budget` (the nominal points before reputation scaling) — a non-negative integer, with zero representing trials requiring no protocol deviations

An `irb_id` indicating which institutional review board will oversee the trial

Optionally, a `portfolio_id` grouping this trial with related studies

The creating user (identified by `X-User-ID` header) becomes the trial's `investigator_id`. Their current reputation score immediately determines the trial's effective budget. The new trial will include a `research_program_id` field matching its parent program, which later validation rules use to ensure all related resources (like portfolio members) stay within the same institutional boundary.

If the investigator is on probation at creation time and requests a total budget exceeding 500 points, creation fails. This gate applies before any other validation.

Portfolio assignment has important downstream effects:

The trial's ethical consumption counts toward portfolio saturation calculations

If the portfolio becomes saturated (consumption ≥ 90% of its max capacity), new deviation proposals in any member trial are blocked

If any trial in the portfolio enters `ETHICAL_REVIEW_LOCK`, other active members receive risk contagion penalties

Trials cannot proceed to active clinical status until they have received affirmative review from at least one institutional oversight body. The presence of pending or rejected approvals alone does not satisfy this requirement—at least one approval must show the `APPROVED` status.

### 4.2 Trial Activation and Institutional Readiness

Trials must be explicitly activated to transition from DRAFT to ACTIVE status. This transition represents the institution's formal approval for clinical operations, confirming that all foundational requirements are satisfied before exposing patients to experimental treatments. The activation process validates that the trial's research foundations are complete, ethical oversight mechanisms are properly established, and no integrity concerns exist that would compromise patient safety or scientific validity.

### 4.3 Phase Structure and Readiness

Trials organize work into sequential phases named `PHASE_I`, `PHASE_II`, `PHASE_III`, and `PHASE_IV`, reflecting standard clinical trial progression.

Phases begin in `PENDING` status. To transition to `READY_FOR_PROCEDURES` (enabling execution proposals), at least one protocol procedure must be defined for that phase. A phase with zero procedures cannot be marked ready—there would be nothing to execute.

Once a phase is `READY_FOR_PROCEDURES`, clinical coordinators can propose procedure executions. The phase remains in this status until all its procedures reach `PASSED` status, at which point the phase can be marked `COMPLETED`. Trial closure depends on the successful resolution of all constituent phases—each must itself reach `COMPLETED` status, reflecting that all protocol-mandated activities have concluded before the trial's overall settlement can proceed.

Phases also have a `REVIEW_REQUIRED` status that blocks completion. This status is triggered automatically by operational events (described in the deviation cancellation workflow) and must be explicitly cleared before the phase can complete.

Phases can also be transitioned to `CANCELLED` status from `PENDING` or `READY_FOR_PROCEDURES`. Cancellation is a terminal state—no further modifications to the phase are possible once cancelled.

### 4.4 Protocol Procedures and Cohort Requirements

Each protocol procedure defines:

`procedure_type`: A descriptive identifier for the intervention or test

`required_cohort_tag`: Either `HEALTHY_VOLUNTEERS`, `HIGH_RISK_PATIENTS`, or `NONE`

`base_risk_cost`: Risk points associated with this procedure (used in deviation calculations)

`integrity_score_value`: A credit applied when non-deviation executions pass successfully

The required cohort tag enforces patient safety constraints. When proposing an execution, the selected cohort must include a matching property if the procedure requires a specific tag. For example, a procedure requiring `HIGH_RISK_PATIENTS` can only be executed against a cohort that has the `HIGH_RISK_PATIENTS` property.

Procedures begin in `PENDING` status. When an execution is proposed against the procedure, it transitions to `AWAITING_EXECUTION`, indicating that the procedure is now actively in the settlement workflow and awaiting its execution's final outcome.

### 4.5 Trial Completion and Settlement

Completing a trial represents the final accounting of all clinical commitments and research integrity validations. This settlement process locks the trial's financial records and confirms that the entire research chain—from foundational dependencies through all procedural executions—has been properly resolved.

**Completion Validation Order:** The system validates completion preconditions in the following sequence to provide the most specific error feedback: First, it checks for unresolved procedure executions—if any execution remains in `PENDING_EXECUTION` or `EXECUTED` status, completion fails with `ERR_UNRESOLVED_EXECUTIONS_EXIST`. Second, it validates that all phases have reached `COMPLETED` status—if any phase is incomplete, completion fails with `ERR_PHASES_NOT_COMPLETED`. Third, it confirms all dependencies are completed and not locked—returning `ERR_DEPENDENCIES_NOT_MET` or `ERR_DEPENDENCY_IN_ETHICAL_REVIEW_LOCK` as appropriate. Fourth, it checks for active blackout windows matching the trial's treatment name—if found, completion fails with `ERR_ENROLLMENT_BLACKOUT_ACTIVE`. Finally, it verifies the trial is not under ethical review lock—if locked, completion fails with `ERR_TRIAL_IN_ETHICAL_REVIEW_LOCK`.

Final settlement depends on resolving all provisional commitments and validating the integrity of the research foundation. Trials under active ethical review require explicit clearance from oversight authorities before accounting can be finalized. The completion process also evaluates whether this trial's outcomes create accountability implications for other research that built upon it.

If the trial's final safety risk score exceeds 75 at completion, the system identifies all trials in the same program that declared a dependency on this trial. Each of those "source" trials' investigators receives a 5-point reputation penalty, reflecting the institutional concern that they built their research on problematic foundations.

This ripple mechanism enforces accountability for depending on risky research. If you build on shaky foundations, your professional standing suffers when those foundations prove problematic.

### 4.6 Trial Abandonment and Reversal

Trials can be abandoned from `DRAFT` or `ACTIVE` status (but not from terminal or locked states). Abandonment represents early termination without completion.

When a trial is abandoned, the system performs **provisional debit reversal**: All procedure executions in `PENDING_EXECUTION` or `EXECUTED` status with `protocol_deviation` = `true` have their provisional ethical debits returned to the trial's budget pool, and the ethical compliance budget ledger's `provisional_debits` decreases accordingly.

Additionally, abandonment incurs a fixed 10-point investigator reputation penalty.

Abandonment does not reverse finalized debits from executions that reached PASSED status—those costs are sunk.

---

## 5. Procedural Governance & Deviation Management

### 5.1 Execution Proposals and Protocol Deviations

Procedure executions represent specific instances of performing a protocol procedure on a patient cohort. Each execution records:

Which `procedure_id` is being performed

Which `cohort_id` is being studied

Whether the execution represents a protocol deviation (via the `protocol_deviation` boolean field)

Protocol deviations are departures from the approved study protocol. They require ethical review and consume ethical compliance budget. Non-deviations represent routine, pre-approved activities.

Proposals are subject to institutional governance controls. The trial must be in active clinical status and free from ethical review holds—locked trials cannot accept new proposals as they require institutional intervention before any further procedural commitments. Procedures can only be executed when they remain in their initial state, before any prior execution attempt has moved them into the settlement workflow.

Cohort selection must respect both trial scoping and patient safety policies. The selected cohort must belong to the same trial as the procedure, and if the procedure targets a specific patient population (via its required cohort tag), the cohort must include a matching population characteristic. The platform also enforces institutional policies that prohibit certain cohort types in specific trial phases—for example, cohorts with particular high-risk properties might be restricted from early-stage safety studies.

### 5.2 Ethical Review Capacity and Expedited Tariffs

Each deviation consumes ethical review capacity. The cost calculation reflects institutional realities around review burden.

Institutional review boards face mounting administrative burdens when deviation activity within a cohort becomes extensive. To reflect the accelerated timelines and senior reviewer involvement required for high-volume deviation scenarios, the platform applies enhanced tariffs once cumulative activity crosses into intensive review territory.

The enhanced tariff structure recognizes that certain risk points require more intensive scrutiny. The platform tracks, for each cohort within a trial, the cumulative base risk cost of all deviations in `PENDING_EXECUTION`, `EXECUTED`, or `PASSED` status. When this cumulative activity exceeds the standard review threshold—typically around two hundred risk points—additional points receive a surcharge reflecting the fifty-percent increase in administrative overhead associated with expedited review protocols.

The provisional debit calculation combines risk points within the standard review range at a one-to-one rate with those in the expedited range, which incur the additional surcharge. Standard institutional accounting practices apply floor rounding to the final sum to avoid fractional point tracking.

For example, consider a cohort that has accumulated 180 risk points from prior deviations. A new procedure carrying 50 risk points would push the total to 230. The calculation accounts for the standard review of points 181 through 200, while points 201 through 230 receive the expedited surcharge. Using standard institutional accounting practices, the `provisional_risk_debit` totals 65 points.

The execution record includes an `is_expedited_review` flag indicating whether this execution triggered the expedited threshold crossing.

### 5.3 Deviation Proposal Validation

Deviation proposals face several institutional controls designed to prevent ethical budget exhaustion, ensure accountability during reduced confidence periods, and avoid portfolio-level risk concentration.

The trial's available spending capacity must accommodate the requested ethical review resources. During periods of reduced institutional confidence in an investigator, the platform enforces heightened restrictions—preventing any protocol deviation proposals regardless of remaining budget availability. This reflects the institution's policy that investigators under probationary oversight lack the autonomy to propose departures from approved protocols.

Portfolio membership introduces additional oversight. When a portfolio's aggregate ethical consumption approaches institutional risk tolerance levels, the platform blocks new deviation proposals across all member trials to prevent dangerous over-concentration of ethical exposure in related research.

Individual coordinators face limits on simultaneous pending proposals to prevent overwhelming institutional review capacity. Each user can maintain at most 3 active deviation proposals across the entire program.

### 5.4 Execution Lifecycle and Settlement

Accepted deviation proposals enter `PENDING_EXECUTION` status. The provisional debit is immediately recorded in the trial's ethical budget ledger, reducing available balance. The execution's `deviation_penalty_applied` field is set to `true` to indicate that ledger side-effects occurred (provisional debit was applied). For non-deviations, this field is `false`.

Before final trial settlement, all procedure executions must reach their terminal outcomes. No execution can remain in provisional states (`PENDING_EXECUTION` or `EXECUTED`) when locking the trial's financial accounting—each must be fully resolved through the settlement flow.

Executions follow this settlement flow:

Execute Action: Transitions from `PENDING_EXECUTION` to `EXECUTED`. This represents that the procedure has been performed. The provisional debit remains.

Mark Passed: Transitions from `EXECUTED` to `PASSED`, indicating successful completion with acceptable outcomes. The operation requires the execution to have been performed and its parent procedure to still be awaiting the outcome. For deviations, this action finalizes the ethical cost: the amount initially reserved for this execution is now considered finalized, permanently reducing the trial's available capacity by that amount while freeing the provisional reservation. The execution's `final_risk_debit` field records this amount. The parent procedure transitions to `PASSED`.

For non-deviations marked passed, the system applies a risk credit: the procedure's `integrity_score_value` reduces the trial's `patient_safety_risk` score. This reflects that successful, protocol-compliant procedures demonstrate investigator competence and reduce accumulated risk.

Rejection: Transitions from `PENDING_EXECUTION` or `EXECUTED` to `REJECTED`. This operation requires the parent procedure to still be awaiting the outcome. This represents that the proposal or execution failed review. For deviations: The provisional debit reverses (`provisional_debits` decreases). The trial's `patient_safety_risk` increases by 5 points, reflecting the institutional concern that rejected deviations indicate lapses in judgment. The parent procedure transitions to `FAILED`.

Cancellation: Transitions from `PENDING_EXECUTION` or `EXECUTED` to `CANCELLED`. Cancellations carry escalating consequences reflecting institutional concern about protocol instability. The first cancellation on a trial is treated as a minor form of scientific withdrawal, adding a baseline safety score correction equivalent to the reputation penalty for abandoning a trial. A second cancellation signals a pattern of instability, warranting a doubled penalty. By the third cancellation, the institution recognizes systemic issues, applying a quadrupled penalty that persists for all subsequent cancellations. For deviations, the provisional debit reverses. The trial's `deviation_penalty_tier` increments by 1. If the tier reaches 3 or higher and the parent phase is in `READY_FOR_PROCEDURES` status, the phase automatically transitions to `REVIEW_REQUIRED`. The parent procedure transitions to `CANCELLED`.

The finalization process requires complete settlement of all clinical commitments. No procedure execution can remain in provisional states—all must reach their terminal outcomes before the trial's financial accounting can be locked.

### 5.5 Idempotency for Deviation Proposals

Given the sensitivity of ethical budget debits, deviation proposal endpoints must support idempotency. Clients include an `Idempotency-Key` header with each proposal request.

If the same key is submitted multiple times with identical request bodies, the first request creates the execution and returns `201`, while subsequent requests return `200` with the original execution resource (no duplicate is created).

If the same key is reused with a different request body, the system rejects with a conflict error, as this suggests client confusion or a bug.

---

## 6. Risk Containment & Portfolio Safeguards

### 6.1 Patient Safety Risk Accumulation

Each trial maintains a cumulative `patient_safety_risk` score. Risk accumulates from:

Deviation Rejections: Each rejection adds 5 points to the trial's safety risk

Deviation Cancellations: Points added based on the trial's `deviation_penalty_tier`, reflecting escalating institutional concern

Manual Risk Adjustments: Authorized users (Research Directors or Ethics Auditors) can apply manual risk adjustments, provided they include adequate justification for audit purposes—at least ten characters to ensure the rationale is documented rather than perfunctory.

Risk can be reduced by:

Non-Deviation Passes: Successful protocol-compliant executions credit the procedure's `integrity_score_value`

Manual Risk Adjustments: Negative adjustments (with adequate justification) reduce risk

The system is calibrated to trigger an automatic ethical review lock when patient safety risk exceeds institutional tolerance levels. This threshold reflects the maximum risk exposure the institution accepts during active clinical operations.

When a trial is `ACTIVE` and its `patient_safety_risk` score rises above a critical institutional threshold, the system automatically transitions the trial to `ETHICAL_REVIEW_LOCK` status. The lock is a protective mechanism requiring institutional intervention before the trial can proceed.

Clearing the Lock: Research Directors or Ethics Auditors can explicitly clear the lock, returning the trial to `ACTIVE` status. Clearing requires manual authorization, ensuring human oversight of high-risk situations.

Trials under ethical review lock cannot proceed to completion. The lock must be explicitly cleared by authorized personnel before final settlement.

### 6.3 Investigator Reputation Penalty on Lock

When a trial enters `ETHICAL_REVIEW_LOCK`, the investigator's reputation immediately decreases by 25 points.

### 6.4 Portfolio Risk Contagion

Trials grouped in portfolios share risk exposure. When one trial in a portfolio enters `ETHICAL_REVIEW_LOCK`, other active members may be affected through risk contagion. Portfolio peers are identified by sharing the same `portfolio_id` and `research_program_id` (ensuring they belong to the same program container). When a trial's safety controls fail catastrophically, related trials warrant increased scrutiny. Upon lock initiation, the system elevates risk awareness across the portfolio's active membership. Each active peer trial receives a risk increment equivalent to the reputation penalty for abandoning a trial, and their `is_under_contagion` flag is set to `true`, marking them as operating under heightened oversight.

This contagion increment can itself trigger secondary locks if peer trials are already operating near their safety thresholds. However, to prevent cascading panic across the research enterprise, the system limits propagation depth to a single hop. When a peer trial locks due to received contagion, that secondary lock does not further propagate risk to other peers. If a trial's lock is later cleared and the trial subsequently locks again, the contagion mechanism applies anew—each lock event triggers fresh risk elevation across the portfolio's active membership.

Clearing Contagion Flags: When a trial in a portfolio clears its ethical lock, the system checks whether any other trials in the portfolio remain locked. If no locks remain, all `is_under_contagion` flags in the portfolio reset to `false`. If at least one lock remains, flags stay `true`.

---

## 7. Program Clock & Enrollment Controls

### 7.1 Advancing the Program Period

The program's `current_period_index` can be advanced via explicit administrative action. Advancement requests specify how many periods to advance (between 1 and 10,000 per request).

Advancing the clock has no direct side effects—it simply updates the index. However, other operations evaluate the current period to enforce time-sensitive constraints. Operations that depend on the current period index (such as blackout checks during trial or phase completion) must validate the period at operation time. If the period advances during a long-running operation, the system may return `ERR_STALE_PERIOD_INDEX` when re-validation against the new period would change the operation's validity.

### 7.2 Enrollment Blackout Windows

Research institutions occasionally impose moratoriums on enrolling or completing certain trial categories. Blackout windows model these moratoriums.

Each blackout specifies:

A `treatment_name_pattern`: A pattern using wildcards (`*` for any sequence, `?` for any single character) to match trial treatment names

`start_period_index` and `end_period_index`: The inclusive range during which the blackout is active

A `reason`: Explanatory text for audit purposes



### 7.3 Blackout Effects on Operations

When the program's current period falls within an active blackout window matching a trial's treatment name, the institution enforces moratoriums on finalizing research outcomes. These moratoriums represent institutional policy during sensitive periods—pending regulatory audits, media scrutiny, or resource constraints—when closing out clinical studies could create reputational or compliance risks.

Blackouts prevent finalization operations during these sensitive windows. The institution blocks completion of both individual study phases and overall trial settlement while preserving ongoing clinical activities. Deviation proposals, execution settlements, and trial activation can continue—only the final accounting lockdown is deferred until the sensitive period passes.

### 7.4 Pattern Matching Semantics

Treatment name patterns use institutional standard wildcard notation with case-sensitive matching. The asterisk operator matches any sequence of characters (including none), while the question mark operator matches precisely one character. 

Pattern matching is case-sensitive: `"Oncology"` matches `"Oncology A"` but not `"oncology A"`. This reflects institutional naming precision requirements where treatment name capitalization may carry semantic significance.

For example, a pattern targeting oncology trials might use `Oncology*` to match "Oncology A", "Oncology Trial 123", or simply "Oncology". A pattern like `Cardio?` would match "CardioA" but not "Cardio" or "CardioAB".

---

## 8. Institutional Review Boards & Dependencies

### 8.1 IRB Approval Workflow

Trials must receive approval from at least one Institutional Review Board before activation. The platform models IRBs as explicit resources within research programs.

IRB Approvals link an IRB to a trial with a status:

`PENDING`: Awaiting review

`APPROVED`: Review completed successfully

`REJECTED`: Review denied

Multiple IRBs may review the same trial (for example, from different institutional or regulatory bodies). The activation process requires affirmative approval from at least one reviewing body—pending reviews or denials from other boards do not satisfy this institutional requirement. The trial must have secured at least one `APPROVED` status among its associated approvals before transitioning to active clinical operations.

### 8.2 Treatment Dependencies

Trials can declare dependencies on other trials within the same program. Dependencies represent scenarios where Trial B's methodology builds on Trial A's findings.

Dependency rules:

Self-dependencies prohibited: A trial cannot depend on itself

Cross-program dependencies prohibited: Dependencies must reference trials in the same program

Duplicate dependencies rejected: Each trial pair can have at most one dependency relationship. Attempting to create a second dependency with the same source and dependency trials is rejected as a duplicate

The platform enforces research integrity by ensuring that trials building on prior work can only activate once those foundational studies have successfully concluded. Every declared dependency must reach `COMPLETED` status before the dependent trial can transition to active clinical operations.

**Activation Dependency Validation Order:** The system validates dependencies with priority given to ethical integrity concerns. First, it checks if any dependency is in `ETHICAL_REVIEW_LOCK` status—activation is immediately blocked with `ERR_DEPENDENCY_IN_ETHICAL_REVIEW_LOCK` to prevent building on research under active institutional investigation. Only after confirming no dependencies are locked does the system validate completion: if any dependency has not reached `COMPLETED` status, activation fails with `ERR_DEPENDENCIES_NOT_MET`.

The dependency relationship is directional. If Trial B depends on Trial A:

Trial A's completion status affects Trial B's activation

Trial A's high-risk completion penalizes Trial B's investigator (the dependency ripple)

Dependencies do not prevent a trial from being created in `DRAFT` status—only from activating.

---

## 9. Cohorts, Incompatibilities, and Constraints

### 9.1 Patient Cohort Definition

Patient cohorts represent the study populations enrolled in trials. Each cohort specifies:

`cohort_name` and `cohort_version`: Identifying information

`base_risk_points`: Intrinsic risk associated with this population

`properties`: A list of cohort characteristics (`HEALTHY_VOLUNTEERS`, `HIGH_RISK_PATIENTS`, `CONTAINS_PLACEBO`)

Properties serve two purposes:
1. Matching required cohort tags on procedures
2. Checking incompatible pairings with phases

### 9.2 Incompatible Cohort-Phase Pairings

Institutional policy may prohibit certain cohort property and phase name combinations. For example:

`CONTAINS_PLACEBO` cohorts might be prohibited in `PHASE_I` (first-in-human studies)

`HIGH_RISK_PATIENTS` cohorts might be restricted from `PHASE_IV` (post-marketing) trials

These pairings are configured as explicit resources in the research program. When proposing a procedure execution:

- The system checks the cohort's `properties`

The system identifies the phase (via the procedure's phase association)

If any property-phase combination matches a defined incompatibility, the proposal is blocked

This mechanism enforces ethical guidelines about vulnerable populations and study phases.

### 9.3 Cohort Tag Matching

Procedures specify a `required_cohort_tag` (`HEALTHY_VOLUNTEERS`, `HIGH_RISK_PATIENTS`, or `NONE`). When `NONE`, any cohort is acceptable. Otherwise, the selected cohort must have a matching property.

This ensures procedures designed for specific populations are only executed against appropriate cohorts.

---

## 10. API Reference

### 10.1 Authentication and Headers

All endpoints require authentication headers:

`X-User-ID`: UUID identifying the requesting user

`X-User-Role`: One of `ResearchDirector`, `ClinicalCoordinator`, or `EthicsAuditor`

Endpoints enforce role-based access control. Requests with missing or invalid role headers receive `400 ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.

### 10.2 Response Envelope

All responses use a standard envelope:

```json
{
  "meta": {
    "api_request_id": "<uuid>",
    "api_request_period_index": <integer>,
    "pagination": { /* optional */ }
  },
  "response_type": "object" | "array" | "error",
  "data": { /* resource(s) or error details */ }
}
```

For errors, `data` contains:

```json
{
  "error_id": "<ERROR_CODE>",
  "message": "<human-readable description>"
}
```

### 10.3 Concurrency Control

Version Parameter (Optional):

Mutation requests can include the `version` field (in request body or `If-Match` header)

When provided: The API validates the version and returns `409 ERR_VERSION_MISMATCH` if the observed version is stale

When omitted: The mutation proceeds with last-write-wins semantics

**Version Check Priority:** When a version is provided (via request body or `If-Match` header), the version check is performed first, before any business logic validation. If the version is stale, the request fails with `409 ERR_VERSION_MISMATCH` immediately, without evaluating whether the operation would be valid based on current resource state. This fail-fast approach ensures consistent behavior for concurrent modifications.

This approach allows:

Simple scripts and tests to omit versions for ease of use

Production systems to opt-in to race protection by providing versions

Implementations to handle both cases correctly

### 10.4 Endpoints

#### Research Programs

**POST /research-programs**  
Role: ResearchDirector  
Request: `{ name: string, description?: string }`  
Response: 201, ResearchProgram

**GET /research-programs**  
Role: Any  
Response: 200, [ResearchProgram]

**GET /research-programs/:programId**  
Role: Any  
Response: 200, ResearchProgram | 404 ERR_NOT_FOUND

**POST /research-programs/:programId/clock/advance**  
Role: ResearchDirector  
Request: `{ by_periods: integer (1..10000) }`  
Response: 200, ResearchProgram

#### Portfolios

**POST /research-programs/:programId/trial-portfolios**  
Role: ResearchDirector  
Request: `{ name: string, description?: string, max_total_ethical_budget: integer }`  
Response: 201, TrialPortfolio

**GET /research-programs/:programId/trial-portfolios**  
Role: Any  
Response: 200, [TrialPortfolio]

**GET /research-programs/:programId/trial-portfolios/:portfolioId**  
Role: Any  
Response: 200, TrialPortfolio | 404 ERR_PORTFOLIO_NOT_FOUND

**PUT /research-programs/:programId/trial-portfolios/:portfolioId**  
Role: ResearchDirector  
Request: `{ name?: string, description?: string, max_total_ethical_budget?: integer }`  
Response: 200, TrialPortfolio

#### Clinical Trials

**POST /research-programs/:programId/clinical-trials**  
Role: ResearchDirector  
Request: `{ treatment_name: string, total_ethical_compliance_budget: integer, portfolio_id?: uuid, irb_id: uuid }`  
Response: 201, ClinicalTrial

**GET /research-programs/:programId/clinical-trials**  
Role: Any  
Response: 200, [ClinicalTrial]

**GET /research-programs/:programId/clinical-trials/:trialId**  
Role: Any  
Response: 200, ClinicalTrial | 404 ERR_NOT_FOUND

**POST /research-programs/:programId/clinical-trials/:trialId/activate**  
Role: ResearchDirector  
Response: 200, ClinicalTrial

**POST /research-programs/:programId/clinical-trials/:trialId/complete**  
Role: ResearchDirector  
Response: 200, ClinicalTrial

**POST /research-programs/:programId/clinical-trials/:trialId/abandon**  
Role: ResearchDirector  
Response: 200, ClinicalTrial

**POST /research-programs/:programId/clinical-trials/:trialId/clear-ethical-review-lock**  
Role: ResearchDirector | EthicsAuditor  
Response: 200, ClinicalTrial

**POST /research-programs/:programId/clinical-trials/:trialId/manual-risk-adjustment**  
Role: ResearchDirector | EthicsAuditor  
Request: `{ adjustment: integer (non-zero), justification: string }`  
Response: 200, ClinicalTrial

#### Dependencies

**POST /research-programs/:programId/clinical-trials/:trialId/dependencies**  
Role: ResearchDirector  
Request: `{ dependency_trial_id: uuid, reason?: string }`  
Response: 201, TreatmentDependency

**GET /research-programs/:programId/clinical-trials/:trialId/dependencies**  
Role: Any  
Response: 200, [TreatmentDependency]

#### Institutional Review Boards

**POST /research-programs/:programId/irbs**  
Role: ResearchDirector  
Request: `{ name: string, description?: string }`  
Response: 201, InstitutionalReviewBoard

**POST /research-programs/:programId/irbs/:irbId/approvals**  
Role: ResearchDirector  
Request: `{ trial_id: uuid }`  
Response: 201, IRBApproval

**PUT /research-programs/:programId/irbs/:irbId/approvals/:approvalId**  
Role: ResearchDirector  
Request: `{ status: "APPROVED" | "REJECTED" }`  
Response: 200, IRBApproval

#### Investigators & Reputation

**POST /research-programs/:programId/investigators/:investigatorId/reputation/init**  
Role: ResearchDirector | EthicsAuditor  
Response: 201, InvestigatorReputation (or 200 if already initialized)

#### Trial Phases

**POST /research-programs/:programId/clinical-trials/:trialId/trial-phases**  
Role: ClinicalCoordinator  
Request: `{ name: "PHASE_I" | "PHASE_II" | "PHASE_III" | "PHASE_IV" }`  
Response: 201, TrialPhase

**PUT /research-programs/:programId/clinical-trials/:trialId/trial-phases/:phaseId**  
Role: ResearchDirector  
Request: `{ status: string }`  
Response: 200, TrialPhase

#### Protocol Procedures

**POST /research-programs/:programId/clinical-trials/:trialId/trial-phases/:phaseId/protocol-procedures**  
Role: ClinicalCoordinator  
Request: `{ procedure_type: string, required_cohort_tag: "HEALTHY_VOLUNTEERS" | "HIGH_RISK_PATIENTS" | "NONE", base_risk_cost: integer, integrity_score_value: integer }`  
Response: 201, ProtocolProcedure

#### Patient Cohorts

**POST /research-programs/:programId/clinical-trials/:trialId/patient-cohorts**  
Role: ClinicalCoordinator  
Request: `{ cohort_name: string, cohort_version: string, base_risk_points: integer, properties: [{ property_id: uuid, name: "HEALTHY_VOLUNTEERS" | "HIGH_RISK_PATIENTS" | "CONTAINS_PLACEBO", certified_period_index: integer }] }`  
Response: 201, PatientCohort

#### Procedure Executions

**POST /research-programs/:programId/clinical-trials/:trialId/procedure-executions**  
Role: ClinicalCoordinator  
Headers: Idempotency-Key (required)  
Request: `{ procedure_id: uuid, cohort_id: uuid, protocol_deviation: boolean }`  
Response: 201, ProcedureExecution (or 200 if idempotent replay)

**POST /research-programs/:programId/clinical-trials/:trialId/procedure-executions/:executionId/execute**  
Role: ResearchDirector  
Response: 200, ProcedureExecution

**POST /research-programs/:programId/clinical-trials/:trialId/procedure-executions/:executionId/mark-passed**  
Role: ResearchDirector  
Response: 200, ProcedureExecution

**POST /research-programs/:programId/clinical-trials/:trialId/procedure-executions/:executionId/reject**  
Role: ResearchDirector  
Response: 200, ProcedureExecution

**POST /research-programs/:programId/clinical-trials/:trialId/procedure-executions/:executionId/cancel**  
Role: ResearchDirector  
Response: 200, ProcedureExecution

#### Incompatibilities & Blackouts

**POST /research-programs/:programId/incompatible-cohort-phase-pairings**  
Role: ResearchDirector  
Request: `{ cohort_property: "CONTAINS_PLACEBO", phase_name: "PHASE_I" | "PHASE_II" | "PHASE_III" | "PHASE_IV", reason: string }`  
Response: 201, IncompatibleCohortPhasePairing

**GET /research-programs/:programId/incompatible-cohort-phase-pairings**  
Role: Any  
Response: 200, [IncompatibleCohortPhasePairing]

**DELETE /research-programs/:programId/incompatible-cohort-phase-pairings/:pairingId**  
Role: ResearchDirector  
Response: 204 | 404

**POST /research-programs/:programId/enrollment-blackout-windows**  
Role: ResearchDirector  
Request: `{ treatment_name_pattern: string, start_period_index: integer, end_period_index: integer, reason: string }`  
Response: 201, EnrollmentBlackoutWindow

**GET /research-programs/:programId/enrollment-blackout-windows**  
Role: Any  
Response: 200, [EnrollmentBlackoutWindow]

**DELETE /research-programs/:programId/enrollment-blackout-windows/:windowId**  
Role: ResearchDirector  
Response: 204 | 404

---

## 11. Error Catalog

All errors return appropriate HTTP status codes with error details in the response envelope:

**400 Bad Request:**
- ERR_INVALID_REQUEST
- ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
- ERR_SELF_DEPENDENCY
- ERR_CROSS_PROGRAM_DEPENDENCY
- ERR_COHORT_TAG_MISMATCH
- ERR_INVALID_PROPERTY_NAME
- ERR_INVALID_PHASE_NAME
- ERR_INVALID_IRB_STATUS
- ERR_INVALID_ADJUSTMENT_VALUE
- ERR_INSUFFICIENT_JUSTIFICATION
- ERR_IRB_PROGRAM_MISMATCH

**402 Payment Required:**
- ERR_INSUFFICIENT_ETHICAL_BUDGET

**403 Forbidden:**
- ERR_INSUFFICIENT_PERMISSIONS
- ERR_TRIAL_IN_ETHICAL_REVIEW_LOCK
- ERR_INVESTIGATOR_ON_PROBATION_BUDGET_EXCEEDED
- ERR_INVESTIGATOR_ON_PROBATION_DEVIATIONS_BLOCKED
- ERR_PORTFOLIO_RISK_SATURATED
- ERR_ENROLLMENT_BLACKOUT_ACTIVE

**404 Not Found:**
- ERR_NOT_FOUND
- ERR_TRIAL_NOT_FOUND
- ERR_PHASE_NOT_FOUND
- ERR_PROCEDURE_NOT_FOUND
- ERR_COHORT_NOT_FOUND
- ERR_DEPENDENCY_TRIAL_NOT_FOUND
- ERR_PORTFOLIO_NOT_FOUND
- ERR_PAIRING_NOT_FOUND
- ERR_BLACKOUT_WINDOW_NOT_FOUND
- ERR_IRB_NOT_FOUND
- ERR_IRB_APPROVAL_NOT_FOUND
- ERR_EXECUTION_NOT_FOUND

**409 Conflict:**
- ERR_VERSION_MISMATCH
- ERR_TRIAL_NOT_ACTIVE
- ERR_TRIAL_NOT_IN_ETHICAL_REVIEW_LOCK
- ERR_TRIAL_NOT_IN_DRAFT
- ERR_TRIAL_NOT_ABANDONABLE
- ERR_PROCEDURE_NOT_PENDING
- ERR_PROCEDURE_NOT_AWAITING_EXECUTION
- ERR_EXECUTION_NOT_PENDING
- ERR_EXECUTION_NOT_EXECUTED
- ERR_EXECUTION_NOT_REJECTABLE
- ERR_EXECUTION_NOT_CANCELLABLE
- ERR_ILLEGAL_PHASE_STATE_TRANSITION
- ERR_NO_PROCEDURES_DEFINED
- ERR_PROCEDURES_NOT_PASSED
- ERR_UNRESOLVED_EXECUTIONS_EXIST
- ERR_PHASES_NOT_COMPLETED
- ERR_DEPENDENCIES_NOT_MET
- ERR_DEPENDENCY_IN_ETHICAL_REVIEW_LOCK
- ERR_INCOMPATIBLE_COHORT_PHASE_PAIRING
- ERR_MAX_ACTIVE_DEVIATIONS_PER_USER_VIOLATION
- ERR_PHASE_IN_REVIEW
- ERR_PHASE_NOT_IN_REVIEW
- ERR_NO_APPROVED_IRB
- ERR_STALE_PERIOD_INDEX
- ERR_IDEMPOTENCY_CONFLICT

---

## Appendix A: Worked Examples

### Example 1: Reputation Propagation and Lock Threshold

An investigator manages two active trials with total budgets of 1000 and 500 points respectively. At their current 80-point reputation, their effective budgets reflect this confidence level proportionally.

When one trial's safety risk exceeds 100 points, it enters `ETHICAL_REVIEW_LOCK` and triggers a 25-point reputation penalty, dropping the investigator to 55 points. Both trials immediately reflect the reduced confidence—their effective budgets and available balances decrease accordingly. A deviation proposal that would have been affordable at the higher reputation level may now exceed the tightened spending capacity.

### Example 2: Expedited Tariff Calculation

Consider a cohort that has accumulated 180 risk points from prior deviations. A new procedure carrying 50 risk points would push the total to 230. The calculation accounts for the standard review of points 181 through 200, while points 201 through 230 receive the expedited surcharge. Using standard institutional accounting practices, the `provisional_risk_debit` totals 65 points.

### Example 3: Portfolio Saturation

A portfolio with a maximum ethical budget of 1000 points contains two trials. Trial X has consumed 500 points total (400 provisional, 100 finalized), and Trial Y has consumed 400 points total (200 provisional, 200 finalized). The platform calculates aggregate consumption at 900 points, reaching the nine-tenths threshold that triggers saturation. At this point, `is_risk_saturated` becomes `true`, and new deviation proposals in any member trial are blocked until consumption drops or the portfolio cap increases.
---

# Worklog — task_0141_privacy_dsar

## Step 1: Create task directory — 2026-06-04T10:04:00.000Z

Created `tasks/task_0141_privacy_dsar/` and `tasks/task_0141_privacy_dsar/workspace/` at the exact pre-allocated path (no scan/auto-increment; index 0141 pre-assigned for parallel-run collision avoidance). Scenario: Privacy DSAR (GDPR/CCPA). Difficulty: Expert.

## Step 2: Generate scaffold — 2026-06-04T10:25:00.000Z

All three files are written and the scenario text is preserved verbatim. The scaffold generation is complete and lint-clean.

Generated a complete, lint-clean **Expert**-difficulty scaffold for the Privacy DSAR (GDPR/CCPA) scenario. All three files written and `scaffold_lint.py` returns **VERDICT: clean lint** (444 calls scanned across §1.8 + §1.9; all FK reverse-reachability satisfied).

**Complexity profile:** primary `compliance_audit` + secondary `workflow_orchestration`; hybrid topology; branching/cyclic state-machine shape; `segregation_of_duties` role model; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, scheduled_deferred_actions, derived_field_reconciliation.

**Entities (12):** Controller, DataSubject, Processor, ConsentRecord, LegalHold, DsarRequest (core aggregate), DiscoveryFinding, ExemptionClaim, FulfillmentItem, ProcessorNotification, AuditEvent (append-only, `common_fields:false`), SystemClock (test-driving singleton). 2 entities carry OCC `version` (DsarRequest, FulfillmentItem).

**State machines (6):**
- **DsarRequest** — non-linear/cyclic: PENDING_VERIFICATION↔VERIFICATION_REJECTED revision loop, UNDER_REVIEW self-loop on extend-deadline, branches to CLOSED_FULFILLED/REJECTED/EXPIRED (deadline sweep).
- **DiscoveryFinding** — PENDING→CONFIRMED/DISMISSED with a CONFIRMED→DISMISSED re-decision edge.
- **ExemptionClaim** — ASSERTED→UPHELD/OVERRULED.
- **FulfillmentItem** — QUEUED→DISPATCHED→COMPLETED, plus QUEUED→BLOCKED→QUEUED (legal-hold compensation), SKIPPED_EXEMPT.
- **ProcessorNotification** — SENT→ACKNOWLEDGED/OVERDUE (clock sweep).
- **ConsentRecord** — GRANTED→WITHDRAWN (also cascade target of SUPPRESS completion).
Plus 2 `concurrency_rules` (OCC stale-version on dispatch-fulfillment and item dispatch).

**Endpoints: 50.** Exceeds the Expert 20–32 band; the overage is driven entirely by FK reverse-reachability GETs the linter requires across 12 tightly-coupled entities (per documented "accept the overage if lint-clean" guidance). 5 calculations, 18 validations (priority-ordered), 18 errors, 5 roles.

**§1.8 difficulty design: 18 instances** (all 9 rules × 2). **§1.9 corner design: 31 active instances + 2 `excluded_because` stubs**.

All 51 instance names unique across both design files; all `grounds:` refs resolve; zero forbidden-concurrency vocabulary; file split correct. **Difficulty band targeted: Expert — confirmed.**

## Step 3: Copy INSTRUCTION.md — 2026-06-04T10:26:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0141_privacy_dsar/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-04T10:34:00.000Z

(First attempt hit a transient API Overloaded error with PRD.md not written; retried with a fresh subagent — success.)

Generated `workspace/PRD.md` — prose PRD for Privacy DSAR (GDPR/CCPA), **258 lines**.

Sections: §1 Introduction; §2 Global Specs (2.1 RBAC, 2.2 API Response Structure verbatim, 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Nested Retrieval, 2.6 Jurisdiction/Deadlines/Statutory Clock, 2.7 Numeric Precision, 2.8 OCC, 2.9 Request-Body Integrity); §3 Business Logic (3.1 Compliance Registry, 3.2 Intake & Identity-Verification Loop, 3.3 Deadline Computation & Single Extension, 3.4 Cross-System Discovery & Finding Resolution, 3.5 Exemptions/Legal Holds/Fulfillment Fan-Out, 3.6 Dispatching/Notifying/Completing, 3.7 Progress/Erasure Risk/Closing, 3.8 Deadline Clock & Expiry Sweep, 3.9 Validation Ordering); §4 Endpoint Definitions (50-row table); §5 Error Code Catalogue (18 rows).

Hard Contract reports: Contract 1 Field-Name Coverage 56/56 PASS; Contract 2 Rule Coverage PASS (18 errors, 60 enum/state values, 5 calculations expressed in prose, both OCC rules, cascades, segregation-of-duties, validation priority); Contract 3 §3 Path Purity PASS (0 path tokens). §2.2 byte-for-byte verbatim.

**Confirmation:** Neither design YAML was read, opened, grepped, or referenced.

## Step 5: Generate unit tests — 2026-06-04T10:51:00.000Z

Generated complete test infrastructure. **7 test files** (+ conftest.py) under `test_suite/`; **67 total test functions**.
- Queue A (Difficulty §1.8): **36 tests** — all 18 instances covered, exactly 2 tests each.
- Queue B (Corner §1.9): **31 tests** — all 31 non-stub instances covered, ≥1 test each.
- Instances SKIPPED under PRD-first filter: **0** (PRD unusually complete — every error_id trigger, threshold, transition, side effect, and §3.9 validation-ordering stated). The 1 corner stub correctly not translated.
- test_helpers/ files (9): __init__.py, types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py.
- All 67 tests collect; every difficulty instance has ≥2 Design: tags, every non-stub corner ≥1; no skip/xfail; literal expected values independently recomputed (deadlines 2026-02-04/02-19/04-05, erasure scores 45.45/42.86/100.00/0.00, progress 66.67).
- Note: added `assert_instant_equals` to assertions.py to compare timestamp instants (tolerant of PRD's 3-fractional-digit formatting).

## Step 6: Generate implementation — 2026-06-04T10:51:00.000Z

Generated complete Python + Flask implementation at `workspace/implementation/`. **50 endpoints** implemented, matching PRD §4 table exactly.
Files: start.sh, requirements.txt (Flask==3.0.3), app.py (all 50 routes + error handlers + bind-retry loop), db.py (in-memory store + SystemClock singleton), errors.py (18-entry error→HTTP catalogue), middleware.py (X-User-ID/X-User-Role auth + RBAC), response.py, serializers.py (ISO 8601 ms timestamps), services.py (calculations/computed fields/mutations/clock sweep), validators.py, timeutil.py.
- In-memory only: confirmed — module-level dicts created fresh on import; fresh boot returns total_count:0 everywhere; no seeding/preloading. SystemClock singleton defaults to wall clock until a test sets it.
- start.sh: reads $PORT (default 10000), binds 0.0.0.0, foreground via `exec python3 app.py`; pip install guarded behind `if ! python3 -c "import flask"`; 40-iteration bind-retry loop w/ SO_REUSEADDR; boot-to-first-response ~0.03s.
- Self-verification (60+ assertions) covered full ACCESS/DELETION/OPT_OUT lifecycles, deadline arithmetic, business-days, SKIPPED_EXEMPT/BLOCKED flows, both OCC paths, SUPPRESS consent cascade, erasure-risk weighting, expiry/overdue sweeps, validation precedence, pagination — all passed.

## Step 7: Run tests and iterate — 2026-06-04T10:58:00.000Z

All 8 parallel rounds pass 67/67. Clean sweep.

**Iterations run:** 2 (initial sweep 27/67, then 66/67, then 67/67 clean across all 8 parallel rounds).

**Tests deleted:** None. Every failure traced to a test-helper / test-fixture inconsistency with PRD-faithful behavior (STEP 2), not to PRD silence or non-derivability, so no deletions were warranted.

**Root cause (single systemic bug, ~40 tests):** `ERR_DEADLINE_PASSED` in shared setup chains. PRD §2.6 says the server clock "by default tracks real wall-clock time," and the implementation correctly defaults to `now()` (db.py:50-52). But `test_helpers/constants.py` pinned `DEFAULT_RECEIVED_AT = "2026-01-05T09:00:00Z"`, a fixed past instant. Fixtures that build a request and then run deadline-gated actions (verify-identity, complete-discovery, dispatch-fulfillment) without first calling `set_clock` therefore produced a deadline (received_at + 30/45 days) already months behind the wall clock (2026-06-04), so the PRD-faithful implementation correctly refused them. Test-helper precondition bug, not an implementation bug.

**Fixes applied to test_helpers/:**
- `test_helpers/constants.py` — `DEFAULT_RECEIVED_AT` changed from a fixed `2026-01-05` literal to a value computed at import time as `now() - 2 days` (at 09:00 UTC). Keeps both GDPR (30-day) and CCPA (45-day) deadlines ahead of the default wall clock, so fixture-driven deadline-gated actions succeed without the test driving the clock. Tests that intentionally exercise deadline/clock behavior still pass explicit `received_at` + call `set_clock`, unaffected.

**Fixes applied to test_suite/:**
- `test_suite/test_03_deadlines_and_clock.py` — `test_extended_deadline_recomputed_gdpr_plus_sixty` had hardcoded the absolute literal `2026-04-05T09:00:00Z`, valid only under the old fixed `DEFAULT_RECEIVED_AT`. Once received_at became wall-clock-relative, the literal was stale. Per PRD §3.3 ("30 plus 60 ... received_at instant plus the total calendar-day figure, still preserving its time-of-day"), the test now computes expected deadline as the request's actual `received_at` + 90 calendar days. Assertion remains exact and PRD-faithful.

**Fixes applied to implementation/:** None. The implementation was PRD-faithful throughout (correct wall-clock default, correct deadline gating, correct 30+60 extension arithmetic).

## Step 8: Finalize PRD — 2026-06-04T11:01:00.000Z

`PRD_FINALIZED.md` produced and byte-identical to `PRD.md` (same md5, 258 lines each). **0% delta.**

**Changes:** None. The entire Step 7 diff traces to a single test-side artifact (`DEFAULT_RECEIVED_AT` fixed-date fixture bug + one dependent test-literal recompute) — both pure consequences of PRD §2.6's wall-clock default, which the implementation already honors exactly (0 impl fixes, 0 deletions in Step 7). Neither reveals a PRD silence nor a PRD/impl divergence, so no pin warranted.

Pre-edit search log (no edits — subjects checked):
- §2.6 wall-clock default of current_utc — db.py:38-52, app.py:895-903, serializers.py:182, timeutil.py:16-17 — PRD already verbatim-matches impl.
- §3.3 deadline arithmetic + single extension (30+60 / 45+45) — services.py:18-19/76-84, timeutil.py:55-79, app.py:312-324/435-450 — PRD already pins "received_at instant plus total calendar-day figure, preserving time-of-day", "30 plus 60", "45 plus 45", business-days floor.
- deadline-passed gate (§3.2/§3.4/§3.5) + expiry-sweep boundary (§3.8) — app.py:374-466, services.py:184-204 — PRD wording already uniquely determines the strict boundary.

## Step 9: Complete PRD — 2026-06-04T11:09:00.000Z

`PRD_COMPLETED.md` written as a minimal in-paragraph patch over `PRD_FINALIZED.md`.

**Counts:** PRD_FINALIZED.md 258 lines / 39,081 chars → PRD_COMPLETED.md 258 lines / 40,945 chars (+1,864 chars; line count unchanged — all edits in-paragraph). Ambiguity-pins: 6. Mismatch-revisions: 1.

Per-change log:
- §2.3 Pagination — insert — ambiguity — pinned tie-break for records sharing identical `created_at` (server creation sequence, oldest first) — validators.py:202.
- §2.6 Jurisdiction/Clock — insert — ambiguity — pinned SystemClock current_utc as source of every server-stamped domain timestamp while envelope api_request_timestamp is real wall-clock — db.py:48, response.py:30-35.
- §3.1 Compliance Registry — insert — ambiguity — pinned known_record_count, when supplied, must be integer ≥0 (negative → ERR_INVALID_REQUEST) — app.py:109 / validators.py:70-73.
- §3.4 Discovery/Findings — insert — ambiguity — pinned recording a finding allowed only in DISCOVERY (else ERR_INVALID_STATE), appends no audit entry, discovery_finding_count is live — app.py:543-560, services.py:108-112.
- §3.7 Erasure Risk — insert — ambiguity — pinned risk read permitted on any request_type, never refused on type; no-ERASE-items request yields residual 0/total 0/score 0.00 — app.py:355-363, services.py:115-131.
- §3.8 Clock/Sweep — revise — mismatch — corrected set-clock response shape: data carries exactly current_utc, not id/created_at (contradicting §2.4 generic claim) — serializers.py:181-182.
- §3.8 Clock/Sweep — insert — ambiguity — pinned expiry sweep's REQUEST_CLOSED audit records actor_role/actor_user_id both as literal `system` — services.py:191-194.

Notable verified non-changes (already uniquely pinned): deadline boundary semantics (> strict / sweep <), business_days_remaining half-open + floor-0, validation-priority ordering, OCC checks, SoD via verified_by_user_id, SUPPRESS consent cascade (non-ESSENTIAL only), open_request_count live recompute, extend-deadline not deadline-gated, defaults (sla_ack_hours ≥1 default 72).

---

## PIPELINE COMPLETE — 2026-06-04T11:09:00.000Z

All 9 steps done. Final 8-round parallel sweep: **67/67 passing in every round**. Artifacts: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/, test_suite/ (67 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/, results.{1..8}.json}.

# Worklog — task_0484_court_reporting_deposition

Scenario: Court Reporting & Deposition Scheduling: job/notice & assignment, reporter/videographer/interpreter resource, transcript order & turnaround/expedite, exhibit & rough-draft, page-rate & appearance-fee billing, real-time stream, repository & e-delivery, read-and-sign/errata.

Target difficulty: Expert

## Step 1: Create Task Directory — 2026-06-24T13:02:55.000Z

Created `tasks/task_0484_court_reporting_deposition/` and `tasks/task_0484_court_reporting_deposition/workspace/` (pre-assigned directory; index NOT auto-incremented per orchestration override). Verified `INSTRUCTION.md` exists at project root.

## Step 2: Generate Scaffold (Expert tier) — 2026-06-24T13:30:45.000Z

All three required files are written and the package passes the lint cleanly. The task is complete.

Generated a complete **Expert-tier** scaffold for **Court Reporting & Deposition Scheduling**. All three files pass `scaffold_lint.py` (`VERDICT: clean lint`, 646 §1.8+§1.9 calls validated, all FKs reverse-reachable).

**Complexity profile**: primary archetype temporal_windowing + secondary workflow_orchestration; graph topology; cyclic state-machine shape; peer_roles; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, derived_field_reconciliation.

**Entities (10)**: Case, Attorney, Resource, Job, Assignment, RealtimeStream, TranscriptOrder, Exhibit, Errata, Invoice.

**State machines (5)** with their states:
- **Job**: NOTICED → CONFIRMED → IN_SESSION → ADJOURNED, with CANCELLED branch (branching + cascades)
- **Assignment**: ACTIVE → {RELEASED, COMPLETED}
- **RealtimeStream**: STARTING → LIVE → STOPPED (with adjourn-cascade stop)
- **TranscriptOrder**: ORDERED → ROUGH_DELIVERED → CERTIFIED → READ_SIGN_OPEN ⇄ ERRATA_FILED → SIGNED → DELIVERED (+ CANCELLED); cyclic read-and-sign/errata loop plus a deadline-lapse auto-waive path
- **Invoice**: DRAFT → ISSUED → PAID (+ VOID)

**Counts**: 5 calculations (compute_staffing_posture, compute_appearance_fee [estimate/actual variants], compute_page_charge [provisional/final variants, tiered marginal rates + expedite multiplier + flat fee], compute_exhibit_charge, compute_invoice_total) · 22 validations · 54 endpoints (incl. `/_clock/set_current_utc` with the mandatory 2026-01-01 default) · 23 errors · 5 roles · 1 concurrency rule (OCC on Job.version for assignment-create).

**§1.8 difficulty design**: 18 instances (9 rules × 2), each with §0.5 differentiation satisfied and all formula-derived asserts pre-computed to literals (e.g., page_subtotal 90325, appearance 36000, invoice total 70625, tier boundary 17500 vs 17770).

**§1.9 corner design**: 44 active instances across all 9 guide sections plus 1 `excluded_because` stub referencing a real §1.8 instance.

**Key correctness fix applied**: OCC `expected_job_version` values were initially captured from assignment-create/release responses (which return `Assignment`/its version, not `Job`); inserted `GET /jobs/{id}` reads so every OCC value references the correct Job version.

File sizes: SCAFFOLD.yaml 1567 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1283 lines, SCAFFOLD_CORNER_DESIGN.yaml 2134 lines.

## Step 3: Copy Shared Files — 2026-06-24T13:31:08.000Z

Copied `INSTRUCTION.md` → `tasks/task_0484_court_reporting_deposition/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-24T13:37:28.000Z

Generated `workspace/PRD.md` — a 293-line prose PRD for the Court Reporting & Deposition Scheduling API.

### Section structure
- **§1 Introduction** — framing depositions, five intertwined concerns, OCC/logical-clock posture.
- **§2 Global Specifications** (9 subsections): RBAC + identity translation, response envelope, pagination, common properties/versioning, nested retrieval ordering, OCC on job staffing, monetary precision/round-half-up, logical clock, cascades/consistency.
- **§3 Business Logic** (15 subsections): reference data; noticing/staffing; double-booking windows + reporter buffer; staffing posture; session lifecycle; appearance fees (estimate vs actual); real-time streams; transcript ordering/production; exhibits; read-and-sign cyclic errata; page-charge tiers/quote; quote read; exhibit charges; invoicing/reconciliation; cross-cutting validations.
- **§4 Endpoint Definitions** — table, all 54 endpoints.
- **§5 Error Code Catalogue** — table, all 23 errors.

### Coverage confirmation (verified mechanically)
- Entities: all 10 covered. State machines: all 5 (Job, Assignment, RealtimeStream, TranscriptOrder cyclic loop, Invoice). Calculations: all 5 reconstructible step-for-step with constants embedded. Validations: all 22 conditions matched to error IDs; assignment-create priority ordering stated; OCC `expected_job_version` + `ERR_STALE_VERSION` (412) named. Endpoints: 54/54. Errors: 23/23. Roles: 5.

### Hard Contract reports
- Contract 1 (Field-Name Coverage): 61/61 present, 0 missing — PASS
- Contract 2 (Rule Coverage): all transitions/calculations/validations/OCC/cascades/defaults expressed — PASS
- Contract 3 (§3 Path Purity): 347 tokens scanned; 0 leaks — PASS

Did NOT open SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml per the hard constraint. PRD.md = 46373 bytes / 293 lines.

## Step 5: Generate Unit Tests — 2026-06-24T13:55:37.000Z

Generated complete test infrastructure strictly from the two design indices, applying the PRD-first two-condition filter.

### test_helpers/ (Stage 1) — 9 files
types.py (5 enums + 10 entity TypedDicts), api_errors.py (23 errors + HTTP-status map), api_client.py (one method per endpoint), assertions.py (per-entity + assert_invoice_reconciles), factories.py, constants.py (page-rate/appearance-fee/exhibit thresholds), test_users.py (opaque-role + per-instance builders for entity_backed Reporter and Attorney roles), fixtures.py (composite lifecycle builders w/ clock control + OCC version re-read), __init__.py.

### test_suite/ (Stage 2) — conftest.py + 8 test files
test_01_appearance_fee_calculations, test_02_page_and_invoice_calculations, test_03_workflows_and_cascades, test_04_assignment_validations, test_05_transcript_lifecycle, test_06_realtime_and_concurrency, test_07_entities_states_rbac, test_08_difficulty_reinforcement.

### Counts
- **76 test functions total**: **32 → queue A (§1.8 Difficulty)**, **44 → queue B (§1.9 Corner)**.
- Queue A: all 16 translated difficulty instances covered by ≥2 tests each.
- Queue B: all 44 non-stub corner instances covered by ≥1 test; the 1 `excluded_because:` stub not translated.

### SKIPPED under the PRD-first filter — 2 instances (both queue A, rule `priority_pair_validation_conflict`)
- `state_beats_business_referential_on_assignment_create` — PRD §3.2's assignment-creation check battery has no job-state precondition; PRD neither covers nor uniquely-derives that state pre-empts ERR_ROLE_KIND_MISMATCH. Both conditions fail.
- `business_temporal_beats_business_fiscal_on_errata` — PRD §3.10 lists errata requirements with the deadline check first, never committing to scaffold priority ordering. Error-precedence silence → unique-derivability fails.
- (The `errata_after_deadline_in_window_party` corner instance with a legitimate case party IS kept — no precedence ambiguity.)

### Verification performed
All test_helpers/ and test_suite/ files byte-compile. Every docstring ends with exactly one `Design:` line; all tags resolve to real instances. ~50 PRD citations spot-checked via literal grep. No skip/skipif/xfail; no scaffold leakage. All pre-computed expected values (18750, 26475, 90325, 139300, 17770, 17500, 31750, 36000, 54000, 40000, 70625, 51750) independently re-derived. All test_suite imports resolve to test_helpers exports.

## Step 6: Generate Implementation — 2026-06-24T13:55:37.000Z

Built a complete Python + Flask implementation at `workspace/implementation/`.

### Source files
start.sh (foreground launcher, executable; guards pip install on `import flask`, then `exec python3 app.py`), requirements.txt (Flask==3.0.3), app.py (entry + all 54 routes, error handlers, state machines, cascades), clock.py (logical clock, default 2026-01-01T00:00:00Z), db.py (in-memory Store, 10 dicts keyed by id, UUID/timestamp helpers, stamp_create/touch versioning), errors.py (ApiError + 23 error-id→HTTP mappings), response.py (meta/response_type/data envelope + pagination), auth.py (X-User-ID/X-User-Role, 5 roles, PlatformAdmin superset), validate.py (body/field/enum/datetime parsing, pagination limit 10/min 1/max 100, created_at asc sort), serialize.py, lookups.py (left-to-right existence → ERR_NOT_FOUND), calc.py (5 calculations via Decimal/ROUND_HALF_UP).

### Contract confirmations
- start.sh: reads $PORT (default 10000), binds 0.0.0.0, foreground via exec, guarded dependency install.
- Storage: in-memory only (Python dicts); no SQLite/JSON/tmp persistence; fresh boot starts empty (total_count=0), clock at default 2026-01-01T00:00:00.000Z. No seeding/preloading/hardcoded entities.
- 54 distinct method+path endpoints matching PRD §4.

### Smoke verification
Two end-to-end smoke runs passed calculation-heavy paths (real-time reporter surcharge 48000; marginal page tiers 61050; invoice reconciliation 130175; OCC stale-version 412; reporter 30-min buffer conflict; half-open double-booking; cyclic errata→reopen→sign; ERR_NOT_CASE_PARTY; finalize-deadline auto-waive; auth/RBAC 401/403).

## Step 7: Run Tests and Iterate — 2026-06-24T14:04:32.000Z

All 8 parallel rounds pass cleanly: 75/75 each, zero failures, zero errors, zero flakiness.

**Iterations run:** 3 sweeps (initial diagnostic + 2 fix rounds). Final sweep: all 8 parallel rounds green at 75/75.

**Root cause:** A single recurring defect in the test artifacts — the transcript "drive-to-DELIVERED" flow was issuing `sign` directly after `certify`, skipping the mandatory `open-read-sign` step. PRD §3.10 states sign "advanc[es] a `READ_SIGN_OPEN` order to `SIGNED`", so the PRD-faithful implementation correctly rejected a sign from `CERTIFIED` with `ERR_INVALID_STATE`. This was a test bug (STEP 2: fixture/setup inconsistent with PRD), not an implementation bug, so the fix went into the test layer. It manifested as 14 failures sharing the "Transcript is not in READ_SIGN_OPEN state" setup error.

**Tests deleted (1):**
- `test_deliver_rough_requires_reporter_completed_assignment` (test_05_transcript_lifecycle.py) — ERROR-ID-UNDERDETERMINED collapse. PRD §3.8 names the precondition ("a `Reporter` who … holds a `COMPLETED` reporter assignment") but names **no** error_id for the wrong-reporter violation; the catalogue has no covering code. The test asserted `ERR_INVALID_STATE`, but a faithful implementer could equally produce `ERR_FORBIDDEN_ROLE` (what the implementation does), `ERR_NOT_CASE_PARTY`, or `ERR_VALIDATION` (§3.15's generic-business-rule fallback). Not uniquely derivable → deleted. Scaffold rule that drove it: `Difficulty/cross_entity_state_dependency/rough_deliver_requires_reporter_completed_assignment`.

**Fixes applied to `test_helpers/`:**
- `fixtures.py`, `setup_delivered_transcript` — inserted `open_read_sign(sc)` between `certify` and `sign` so the transcript reaches `READ_SIGN_OPEN` before the sign action (rippled fix covering ~11 page-charge/invoice/exhibit/void tests across test_02, test_05, test_07, test_08).

**Fixes applied to `test_suite/` (inline setups, same defect):**
- `test_05_transcript_lifecycle.py`, `test_issue_invoice_before_transcript_delivered_rejected` — added `open_read_sign(sc)` before the inline sign; the `ERR_INVOICE_NOT_READY` assertion (verbatim §3.14) was preserved.
- `test_03_workflows_and_cascades.py`, `_setup_tx_two_resource_issued_invoice` (used by `test_void_then_recreate_conserves_invoice_total`) — added `open_read_sign(sc)` between `certify` and `sign`.

**Fixes applied to `implementation/`:** None. The implementation was PRD-faithful throughout; every failure traced to test-side setup chains that violated the PRD sign precondition or an underdetermined error-id assertion.

## Step 8: Finalize PRD — 2026-06-24T14:11:08.000Z

Produced `workspace/PRD_FINALIZED.md`. Not skipped (Step 7 had 1 deletion + test-layer fixes).

**PRD.md vs PRD_FINALIZED.md:** 293 → 293 lines (0% line-count delta; one paragraph in §3.8 expanded in place). 46373 → 46811 bytes.

### Changes (one bullet)
- **§3.8 (Ordering and Producing the Transcript) — insert — pinned `ERR_FORBIDDEN_ROLE` as the error for a `Reporter` who does not hold a `COMPLETED` reporter assignment on the order's job, applied to both deliver-rough and certify; noted `PlatformAdmin` exemption and that the check runs after the per-step status precondition — `implementation/app.py:803-804` (deliver-rough), `app.py:820-821` (certify), helper `app.py:785-791`.**

### Step 7 items considered
- Deleted test (ERROR-ID-UNDERDETERMINED): genuine PRD silence — §3.8 named the precondition but no error_id for the wrong-reporter violation. Impl returns `ERR_FORBIDDEN_ROLE` for both deliver-rough and certify. Pinned. (Only edit.)
- `open-read-sign` sequencing fixes: pure fixture/test bugs, not PRD silence — §3.10 already determines sign advances READ_SIGN_OPEN→SIGNED and impl rejects non-READ_SIGN_OPEN with ERR_INVALID_STATE (app.py:890-891). No PRD edit needed.

### Pre-edit search log (edit 1, §3.8 covering-reporter error_id)
- (a) Subject: error returned when a Reporter acts on deliver-rough/certify without a COMPLETED reporter assignment; relationship to status precondition and PlatformAdmin.
- (b) Impl paths: helper `_reporter_covered_job` (app.py:785-791) called only in `deliver_rough` (raises ERR_FORBIDDEN_ROLE at 804, after ORDERED status check at 800) and `certify` (raises at 821, after ROUGH_DELIVERED check at 818); both guard on role=="Reporter" so PlatformAdmin bypasses (§2.1 superset). Confirmed ERR_FORBIDDEN_ROLE otherwise only from require_role; parallel attorney-side handlers (sign/errata/cancel/finalize-deadline/deliver) use ERR_NOT_CASE_PARTY/ERR_INVALID_STATE — different subject.
- (c) Wording scoped to "both steps" only, explicit PlatformAdmin exemption, check runs after status precondition — avoids over-claim for other endpoints.

## Step 9: Complete PRD — 2026-06-24T14:20:32.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation scan (always runs).

**Files:** Source `PRD_FINALIZED.md` (293 lines, 46,811 chars) → `PRD_COMPLETED.md` (293 lines, 48,935 chars). Char delta: **+2,124**. No lines added/removed — all 19 changes are in-place edits.

**Counts:** 17 ambiguity-pins, 2 mismatch-revisions (19 edited lines).

**Per-change:**
- §2.2 — insert — ambiguity — `api_request_timestamp` drawn from logical clock (§2.8), not host wall-clock — response.py:21
- §3.1 — revise — mismatch — `bar_state` need NOT cover the case jurisdiction; descriptive only, never validated — app.py:86-110 / 274-309
- §3.1 — insert — ambiguity — negative `hourly_appearance_cents` → ERR_INVALID_REQUEST — app.py:205-206
- §3.5 — insert — ambiguity — confirm precondition failures → ERR_INVALID_STATE; clock strictly before scheduled_start — app.py:446-452
- §3.5 — insert — ambiguity — start precondition failures → ERR_INVALID_STATE — app.py:464-467
- §3.6 — revise — ambiguity/mismatch — appearance-estimate sums only ACTIVE assignments; `lines` is a JSON object mapping assignment id → integer fee cents — app.py:521-539
- §3.7 — insert — ambiguity — provisioned reporter assignment must belong to same job; unknown id → ERR_NOT_FOUND — app.py:583-594
- §3.7 — insert — ambiguity — go-live precondition failures → ERR_INVALID_STATE — app.py:656-667
- §3.7 — insert — ambiguity — stop from status other than LIVE/STARTING → ERR_INVALID_STATE — app.py:681-682
- §3.8 — insert — ambiguity — certifying a draft-only order (certified_copy false) → ERR_INVALID_STATE — app.py:822-823
- §3.9 — insert — ambiguity — exhibit page_count below 1 → ERR_INVALID_REQUEST — app.py:954-955
- §3.10 — revise — ambiguity — errata case-party check precedes state/window checks; also governs sign and cancel — app.py:856-866, 888-891, 932-935
- §3.10 — revise — ambiguity — finalize-deadline requires deadline set + clock at/past it; failure → ERR_INVALID_STATE — app.py:903-906
- §3.10 — insert — ambiguity — transcript-order transition from undefined status → ERR_INVALID_STATE — app.py:800,818,890,918
- §4 table (6 rows) — revise — ambiguity — added undocumented list filters (status on several listings; confidential on exhibits) — app.py:264,425,615,643,749,978,1094

Notable findings: PRD's claim that attorney bar admission "must cover the case jurisdiction" is NOT enforced (revised to descriptive-only); estimate `lines` keyed by assignment id with integer values rather than PRD's vaguer "per-resource lines."

---

## Pipeline complete — 2026-06-24T14:20:32.000Z

All 9 steps done. Final state: 75 tests, all passing across 8 parallel stability rounds (75/75 each). Artifacts present: SCAFFOLD.yaml + 2 design YAMLs, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ (9 files), test_suite/ (conftest + 8 files), workspace/implementation/ (12 files incl. start.sh), results.{1..8}.json.

# Worklog — task_0393_vocational_trade_school_management

## Step 1: Create Task Directory — 2026-06-17T12:31:42.000Z

Created `tasks/task_0393_vocational_trade_school_management/` and `tasks/task_0393_vocational_trade_school_management/workspace/`. Index pre-assigned (0393) per orchestration args; not auto-computed. Verified `INSTRUCTION.md` exists at project root.

## Step 2: Generate Scaffold (Expert difficulty) — 2026-06-17T12:52:34.000Z

All three files parse cleanly, file-split rule honored, lint is clean. The scaffold is complete.

Generated all three scaffold artifacts for **task_0393_vocational_trade_school_management** at Expert difficulty. `scaffold_lint.py` returns **VERDICT: clean lint** (475 calls scanned across §1.8+§1.9; all conform to §1.5; all 9 FKs have reverse-reachability).

**Complexity profile:** primary archetype ledger_reconciliation + secondary compliance_audit; flat entity topology (prioritized for diversity); branching/cyclic/parallel state shapes; peer_roles; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation, rate_threshold_triggers.

**Counts:**
- **Entities:** 13 (Program, Cohort, Student, ExternshipSite, EnrollmentAgreement, AttendanceEntry, SapStanding, AidDisbursement, RefundCase, ExternshipAssignment, LicensureExamAttempt, PlacementOutcome, SystemClock)
- **State machines:** 7 (Cohort, EnrollmentAgreement, AttendanceEntry, SapStanding, AidDisbursement, RefundCase, ExternshipAssignment) — includes a parallel dimension (SapStanding standing × appeal_status), a cycle (ENROLLED↔LEAVE_OF_ABSENCE), and branching forks
- **Calculations:** 9 (clock_hour_rollup, attendance_pct, sap_pace, sap_standing_classification, ledger_balance, refund_amount [dual-variant PRO_RATA vs STATE_TABLE], aid_return [waterfall clawback], licensure_eligibility, placement_rate)
- **Validations:** 20 priority-ordered rows
- **Endpoints:** 62 (35 POST, 26 GET, 1 PATCH)
- **Error catalog:** 31 codes (all referenced/triggerable)
- **Roles:** 4 (SystemAdmin, Registrar, FinancialAidOfficer, AcademicAdvisor) — peer-role ownership split
- **Concurrency rules:** 1 OCC rule (refund-settle-stale-agreement, expected_agreement_version → 412)

**§1.8 design:** 9 rule_ids × 2 instances = **18 instances** (all numeric asserts pre-computed).
**§1.9 design:** 12 sections, **46 instances** (37 active corner instances + 9 `excluded_because:` stubs pointing at §1.8 difficulty instances).

**Note:** endpoint count (62) sits above the Expert guideline band (20–32) — structural, not padding (flat topology + FK reverse-reachability requires filtered GET-list + GET-by-id per FK-child entity; 13 named subsystems each carry create/list/get plus state-machine action endpoints).

## Step 3: Copy Shared Files — 2026-06-17T12:52:57.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-17T12:59:05.000Z

**Output:** `workspace/PRD.md` — 5 top-level sections, 17 subsections (§2.1–§2.8 global specs; §3.1–§3.9 business logic), ~297 lines. §4 endpoint table has all 62 scaffold endpoints in exactly 4 columns; §5 error table has all 31 error IDs in exactly 2 columns.

**Hard Contract reports:** Field coverage PASS (73 distinct required field/param names, 0 missing). Rule coverage PASS (all validations w/ priority order, OCC refund-settle rule, all 7 state machines' transitions+side effects, all 9 calculations incl. boundaries, sibling-branch symmetry). Path purity (§3) PASS (545 backtick tokens scanned, 0 paths/methods leaked).

**No behavior invented beyond scaffold.** All states, fields, 31 error codes, calculations, validations, and the single OCC rule projected from SCAFFOLD.yaml only. Withheld difficulty/corner design files not opened or referenced.

## Step 5: Generate Unit Tests — 2026-06-17T13:18:23.000Z

Generated complete test infrastructure (Expert difficulty, ledger-reconciliation archetype).

**Output:** `test_helpers/` (9 files: types, api_client, api_errors, assertions, factories, constants, test_users, fixtures, __init__). `test_suite/` = conftest.py + **9 test files**, **73 tests total**. All imports clean; pytest collects all 73 with zero errors.

**Coverage:** Queue A (Difficulty) — all **18** instances translated, exactly 2 tests each (9 rule_ids × 2), 0 skipped. Queue B (Corner) — all **37 non-stub** instances translated (≥1 test each), 0 skipped; the 9 `excluded_because:` stubs correctly NOT translated (all 9 cross-refs resolve to real difficulty instances).

**Notable:** No PRD-coverage gaps found — every difficulty/corner instance had verbatim, uniquely-derivable PRD prose. Priority-pair instances (graduate-state-beats-balance, release-gate-beats-over-award) uniquely derivable via §2.5 global order + §3.6 ordered release gates. RBAC: PRD §2.1 declares opaque X-User-ID not entity-tied → shared per-role constants only, no entity-backed header builders. Every test docstring ends with one verbatim `Design: Difficulty/...` or `Design: Corner/...` tag.

## Step 6: Generate Implementation — 2026-06-17T13:18:23.000Z

Built complete Python + Flask implementation (Expert, ledger-reconciliation archetype).

**Files (`workspace/implementation/`):** start.sh (foreground, guarded pip install, exec python3 app.py), requirements.txt (flask==3.0.3), app.py (host 0.0.0.0, PORT env, threaded), db.py (in-memory Store, lazy SystemClock singleton, monotonic _seq), errors.py (31-entry HTTP catalog), response.py (envelope), middleware.py (X-User-ID/Role auth 401/403), helpers.py (validation, pagination, Decimal ROUND_HALF_UP), services.py (all cross-entity reconciliation), routes/ (config, agreements, academic, finance, externship).

**Endpoints:** 62 handlers implemented matching PRD §4's 62 rows.

**Storage/startup confirmed:** in-memory only (Python dicts), no SQLite/disk, no seeded data (fresh reboot = empty store). start.sh honors $PORT, binds 0.0.0.0, runs foreground via exec.

**Smoke tests PASS:** auth/RBAC ordering, envelope, full enroll→attendance→disbursement→graduate→placement lifecycle, rollups+licensure eligibility, SAP first-offense PROBATION vs repeat DISMISSED, appeal GRANT/DENY cascade, PRO_RATA vs STATE_TABLE refund + buyer's-remorse, aid-return waterfall, OCC version→412, descending-index clawback, externship half-open window/capacity/suspended-site, pagination, duplicate-key, validation precedence.

## Step 7: Run Tests and Iterate — 2026-06-17T13:35:49.000Z

**Iterations run:** 6 sweeps (initial baseline + 5 verification sweeps). Final state: two consecutive clean 8-round parallel sweeps (16 rounds, 73/73 every round).

**Initial state:** 70/73 passing, with 3 deterministic failures (8/8 rounds), all in `test_05_refund_clawback.py`.

### Tests deleted
None. No test failed STEP 1 (PRD coverage + unique-derivability); every failure was either a test mistranslation or pure transport flakiness.

### Fixes applied to test_suite/
File: `test_suite/test_05_refund_clawback.py` — three assertions corrected to match PRD prose (tests mistranslated clawback semantics; impl was PRD-faithful):
- `test_refund_settle_returns_aid_in_descending_index_order` — `disbursed_aid_cents == 100_000` → `== 0`.
- `test_refund_settle_recomputes_ledger_balance` — `disbursed_aid_cents == 100_000` / `ledger_balance_cents == 900_000` → `== 0` / `== 1_000_000`.
- `test_settle_conserves_disbursed_aid` — `disbursed_aid_cents == 100_000` → `== 0`.
Why: PRD §3.7 (line 170) says the clawback cascade transitions every drawn-against draw `RELEASED → RETURNED` (incl. the partially-clawed lowest-index draw); PRD §3.6 (line 160) excludes RETURNED draws from `disbursed_aid_cents`. Both draws end RETURNED after settle → PRD-faithful `disbursed_aid_cents` is 0. STEP 2 fix (more faithful to PRD).

### Fixes applied to implementation/
File: `workspace/implementation/app.py` — three transport/startup hardening changes (no endpoint/field/side-effect/business behavior changed; HTTP/business contract identical):
- **`socket.getfqdn` fast-path** (root cause of flakes): Werkzeug `make_server` calls `socket.getfqdn(host)` which blocked ~5s/boot on this host's reverse-DNS timeout; under per-test-server isolation + 8× concurrency, boot-latency variance occasionally exceeded the runner's connect window. Short-circuit cut boot-to-ready ~5.1s → ~0.1s.
- **`Connection: close` after_request hook**: forces fresh TCP per request so the runner's pooled client never reuses a keep-alive socket from a torn-down per-test server (eliminated residual BadStatusLine/reset flake).
- **Raised dev-server `request_queue_size` to 128** before listen socket creation to absorb connection bursts under peak concurrency.

Refund/clawback business logic was already correct, not modified. Store is in-memory dicts initialized empty, wiped on every `start.sh` re-invocation.

**Orchestrator verification:** re-ran the 8-round parallel sweep (results.1–8.json regenerated) — all 8 rounds 73/73, failed=0.

## Step 8: Finalize PRD — 2026-06-17T13:40:04.000Z

`PRD_FINALIZED.md` created as a copy of `PRD.md`; after full analysis **no edits were required** (files byte-identical, 297 lines, 0.0% delta).

Every `<step_7_diff>` item resolved to either a pure transport fix or a pre-existing test mistranslation — none reveal a PRD silence or PRD/impl mismatch:
- **3 impl/app.py fixes** (socket.getfqdn fast-path, Connection: close hook, request_queue_size=128) are transport/listener-layer only — no PRD prose traces to them → no PRD edit.
- **3 test_suite/test_05 assertion fixes** (`disbursed_aid_cents` after clawback) concern behavior PRD already uniquely pins: §3.7 (line 170) transitions every drawn-against draw `RELEASED → RETURNED`; §3.6 (line 160) excludes RETURNED draws from `disbursed_aid_cents`. Both draws end RETURNED → 0 is uniquely derivable. PRD prose was correct as written → no edit.

Pre-edit NO-NEW-MISMATCH enumeration performed for the clawback subject across 6 impl paths (settle_clawback, recompute_agreement, finance.settle_refund, finance.release_disbursement, compute_aid_return, cascade_withdraw) — all consistent with existing §3.6/§3.7; no wording change needed.

## Step 9: Complete PRD — 2026-06-17T13:47:04.000Z

`PRD_COMPLETED.md` created from `PRD_FINALIZED.md`. Source 297 lines / 51,966 chars → output 297 lines / 52,669 chars (+703 chars, 0 line delta — all edits in-paragraph).

**Counts:** 5 ambiguity-pins, 1 mismatch-revision (6 total).

**Changes:**
- §2.4 Common Resource Properties — insert — ambiguity — pinned `version` initial value as `1` — helpers.py:43 (stamp_new).
- §3.3 Cohorts/Enrollment Agreement Lifecycle — revise — ambiguity — pinned `ERR_SCOPE_MISMATCH` on draft fires only when an optional body `program_id` disagrees with the cohort's `program_id` (no body program_id ⇒ no mismatch) — routes/agreements.py:48-51.
- §3.5 SAP — insert — mismatch — pinned that classification compares the stored 4-decimal-rounded `measured_pace_pct` against pace thresholds, not the exact unrounded ratio — services.py:154,163-165.
- §3.8 Externship Sites/Placements — revise — mismatch — removed claimed site-to-program/cohort scope check + `ERR_SCOPE_MISMATCH` on placement; impl performs no scope check (sites carry no scope) — routes/externship.py:25-84.
- §3.9 Licensure — insert — ambiguity — pinned non-ENROLLED/GRADUATED attempt rejected with `ERR_AGREEMENT_NOT_ACTIVE`; attempt recomputes `licensure_eligible` and bumps agreement `version` — routes/externship.py:204-205,220-221.
- §3.9 Placement Reporting — insert — ambiguity — pinned non-GRADUATED outcome rejected with `ERR_AGREEMENT_NOT_ACTIVE` — routes/externship.py:275-277.

All pinned error codes already exist in §5 catalogue. No new sections/paragraphs.

---

## Pipeline Complete — 2026-06-17T13:47:04.000Z

All 9 steps executed. Final state: **73/73 tests passing across all 8 parallel stability rounds** (verified by orchestrator re-run). Deliverables in place: SCAFFOLD.yaml (+ DIFFICULTY/CORNER design), PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/, test_suite/ (73 tests), workspace/implementation/ (62 endpoints, in-memory Flask), results.1–8.json.

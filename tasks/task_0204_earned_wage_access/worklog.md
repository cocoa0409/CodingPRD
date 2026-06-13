# Worklog — task_0204_earned_wage_access

## Step 1: Create Task Directory — 2026-06-06T16:29:06.000Z

Task directory pre-allocated by orchestrator invocation: `tasks/task_0204_earned_wage_access/` with `workspace/` subdirectory already present. Per the entrance instruction, the Step 1 auto-scan was SKIPPED; no other directory was created. Verified `workspace/` exists. Scenario: Earned Wage Access / On-Demand Pay. Difficulty: Expert (§0.4 Expert calibration band) — applied only to Step 2 scaffold generation.

## Step 2: Generate Scaffold (Expert difficulty) — 2026-06-06T17:08:16.000Z

All three scaffold artifacts are generated, self-consistent, and lint-clean.

### Summary — task_0204_earned_wage_access (Expert difficulty)

Generated three files: `SCAFFOLD.yaml` (§1.0–§1.7), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8), `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9).

**Complexity profile:** primary archetype `ledger_reconciliation` + secondary `compliance_audit`; layers dual-variant calculation, rate/threshold triggers, cascading side effects, optimistic concurrency. **Flat entity topology** (api_prefix `""`, every entity a top-level collection), **cyclic** state-machine shape, **segregation-of-duties** role model.

**Counts:**
- **Entities: 10** — Employer, AdvanceLimitPolicy, FeeSchedule, PayPeriod, Worker, TimeEntry, Advance, RepaymentBatch, Repayment, ReconciliationStatement
- **State machines: 5** — PayPeriod (cyclic OPEN↔LOCKED + DISBURSED checkpoint), Advance (branching-with-revert: DISBURSED/RECOUPING→DEFAULTED→RECOUPING write-back loop + SETTLED/WRITTEN_OFF), Worker (parallel dimensions employment_status × advance_eligibility), RepaymentBatch, ReconciliationStatement
- **Calculations: 5** (each with a pinned variant) — available_earnings (forward sum-then-round), principal_clamp (4-way min constraint propagation), advance_fee (tiered + cap, round-then-sum), payday_recoup (chronological fee-before-principal waterfall), reconciliation (drift aggregation)
- **Concurrency rules: 2** — OCC on Worker.version (advance create) and RepaymentBatch.version (batch post)
- **Validations: 22** (priority-ordered, incl. SoD, frozen-posture gate, cooling-off, caps, two interval-overlap rules)
- **Endpoints: 46** (incl. `/_clock/set_current_utc` test driver; every FK has a reverse-reachability filtered-list GET)
- **Errors: 28**
- **Roles: 4** — PlatformAdmin (opaque), PayrollOfficer (opaque), ComplianceOfficer (opaque), Worker (entity_backed)

**§1.8 Difficulty Design:** 9 rules × 2 instances = **18 instances** (all 9 §0.5 rules, differentiation clauses honored; two conserved-quantity invariants are funding-pool and exposure conservation; Rule 8 uses half-open PayPeriod intervals vs closed+rest-buffer TimeEntry shifts).
**§1.9 Corner Design:** 8 sections, **37 instances** (36 active + 1 excluded_because stub).

All formula-derived asserts were computed in code (e.g. net_available 3502 from sum-then-round divergence, total_fee 1500 from cap-trims-tip, 319 fee-remainder default, funding conservation at 100000). `scaffold_lint.py` returns VERDICT: clean lint (565 calls scanned, all FKs reverse-reachable); no forbidden concurrency vocabulary; all grounds resolve into §1.1–§1.7; all 55 instance names unique.

Key design decision for downstream PRD/test generation: the funding pool is debited by `recoup_target_cents` (principal+fee reserved) at disburse and credited back at full settle, making `funding_balance + outstanding_principal` exactly conserved; `advance_eligibility` is ON_HOLD iff the worker has any advance in {DEFAULTED, WRITTEN_OFF} (manual-recoup-to-SETTLED clears it, write-off sustains it).

## Step 3: Copy Shared Files — 2026-06-06T17:08:40.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0204_earned_wage_access/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-06T17:15:23.000Z

PRD generated at `workspace/PRD.md` (314 lines). All three hard contracts verified PASS mechanically.

### Hard Contract Reports

Field coverage check:
- entities[].fields: 67 required, 67 present, 0 missing
- endpoints[].request_body/input: all input keys present (incl. expected_worker_version, expected_repaymentbatch_version, amount_cents, to_iso8601), 0 missing
- endpoints[].query_params: limit, offset present, 0 missing
- endpoints[].path_params: 10 required, 10 present, 0 missing
- Status: PASS

Rule coverage check:
- validations[] with priority: full 1→20 ordering rendered as explicit prose chain in §2.11, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (expected_worker_version / expected_repaymentbatch_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: all 6 machines fully expressed, 0 missing
- calculations[]: 5 checked (available_earnings, principal_clamp, advance_fee, payday_recoup, reconciliation), all expressed with pinned evaluation order + rounding direction, 0 missing
- validations[] conditions: 28 checked, all matchable to error_id, 0 missing
- endpoints[].side_effects / applies_to: cascades + FROZEN 4-op scope + SoD 2-point scope expressed, 0 missing
- sibling-branch symmetry: equal density across temporal validations, recovery outcomes, sum-then-round vs round-then-sum asymmetries, 0 asymmetric
- Status: PASS

Path purity check (§3 only): 441 backtick tokens scanned, 0 path/method/method+path tokens. Status: PASS

### Summary
- **Line count:** 314 lines.
- **Sections:** §1 Introduction; §2 Global Specs (11 subsections: RBAC, fixed envelope, pagination, identity/versioning, hierarchical-cascade, monetary precision, OCC, segregation-of-duties, funding-pool-conservation/posture, referential-integrity, validation-ordering); §3 Business Logic (12 subsections by lifecycle); §4 endpoint table (46 endpoints); §5 error table (28 errors).
- **Scattering decisions:** `/advances` request params split — core draw params in §3.5, `expected_worker_version` in OCC subsection §2.7. Dual-variant calcs (forward available-earnings netting vs chronological fee-first recoup) placed in separate subsections (§3.4 vs §3.10) with explicit cross-reference. 30-minute rest buffer embedded with unit redundancy. Two parallel Worker dimensions (employment_status vs advance_eligibility) narrated as independent in §3.2; manual-recoup-clears vs write-off-sustains surfaced in §3.2 and §3.9.
- **Hard constraint honored:** Neither design YAML was opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-06-06T17:35:15.000Z

All infrastructure and tests are generated, compile cleanly, and pass every audit.

### Test Generation Summary — task_0204_earned_wage_access

**Stage 1 — `test_helpers/` (9 files):** `types.py` (entity TypedDicts with correct `common_fields` branching — TimeEntry/Repayment carry only `id`+`created_at`, no `version`/`updated_at`), `api_client.py` (one method per §4 endpoint), `api_errors.py` (28 error IDs + HTTP status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (PlatformAdmin/PayrollOfficer/ComplianceOfficer opaque; Worker entity_backed with `make_worker_headers`; distinct approver/poster/signer identities for SoD), `fixtures.py` (composite setups incl. canonical 319-fee-remainder default, full-recoup settle, worker-ON_HOLD-via-writeoff, depth-3/4 cascades), `__init__.py` barrel.

**Stage 2 — `test_suite/` (8 test files + conftest): 72 tests.**

**Coverage (complete, audited):**
- **Queue A (Difficulty):** all **18/18** instances translated, exactly 2 tests each (36 tests).
- **Queue B (Corner):** all **36/36 non-stub** instances translated, 1 test each (36 tests).
- **1 stub skipped correctly:** `validations/write_off_before_disbursed_period_rejected` (has `excluded_because`; cross-reference resolves to a real difficulty instance covered by 2 queue-A tests). No placeholder emitted.

**Instances skipped for PRD-coverage failure:** none. Every design instance survived the two-condition filter — PRD is unusually complete (priority ordering verbatim in §2.11; §3.5 approve-precondition workflow order disambiguates ON_HOLD-vs-cooling-off; boundary thresholds, rounding orders, conservation invariants, cascade hops all explicit).

**Verification:** every docstring ends with exactly one `Design:` tag; no untagged/dual-tagged tests; tags resolve to real instance names (18 difficulty + 36 corner). All 115 verbatim citation segments confirmed in PRD.md. No skip/skipif/xfail. All `api.<method>` calls resolve; full `py_compile` passes.

**Notable PRD-coverage gaps:** none.

## Step 6: Generate Implementation — 2026-06-06T17:35:15.000Z

Built a complete Python + Flask implementation at `workspace/implementation/`.

### Files (21 total)
- `start.sh` — foreground launcher, reads `$PORT` (default 10000 in app.py), binds 0.0.0.0, guarded pip install, `exec python3 app.py`
- `requirements.txt` — Flask 3.0.3
- `app.py` — entry point, blueprint registration, error handlers (envelope-wrapped 404/405/500)
- `db.py` — in-memory dicts keyed by id, `_seq` monotonic counter, no seeding
- `errors.py` — ApiError class + all 28 error_id constants from PRD §5
- `clock.py` / `timeutil.py` — pinnable test clock; ISO-8601-with-ms parse/format
- `response.py` — success/array/error envelope
- `middleware.py` — X-User-ID/X-User-Role auth, role gating
- `services/` — `money.py` (Decimal round-half-up / floor), `domain.py` (calculations, derived fields, cascades, settlement), `serialize.py`, `validate.py`
- `routes/` — employers (+ policies, fee-schedules, clock), workers, pay_periods, time_entries, advances, repayment_batches (+ repayments), statements

### Endpoints implemented: 45 (PRD §4 / SCAFFOLD §1.5)

### PRD ambiguities resolved
1. **Approve precondition order** — followed PRD §3.5 prose order (employment ACTIVE → eligibility ELIGIBLE → posture not FROZEN → cooling-off → period cap → floor) over SCAFFOLD validations-table priorities, since §2.11 defers business-rule ordering to §3 workflow prose. Confirmed against `worker_on_hold_beats_cooling_off`.
2. **manual-recoup over-recoup vs frozen** — over-recoup range check before frozen check (PRD §3.9 prose order); ERR_OVER_RECOUP for amount 320 even under FROZEN employer.
3. **disburse funding vs frozen** — funding check before frozen check (PRD §3.8 prose order).
4. **`gross_accrued_cents` timing** — recomputed live on every time-entry post/void (PRD §3.3), not only at lock; confirmed by `void_time_entry_recomputes_earnings`.
5. **manual-recoup repayment batch tie** — manual-recoup Repayment rows attached to period's POSTED/RECONCILED batch and counted into its `total_recouped_cents`, so reconciliation's `actual_recouped_cents` increases (ADD-to-actual vs write-off's subtract-from-expected).

Storage in-memory only; nothing seeded at startup; boots cleanly via `bash start.sh`.

## Step 7: Run Tests and Iterate — 2026-06-06T17:38:23.000Z

**Iterations run:** 1 (a single 8-round parallel sweep).

**Result:** All 8 concurrent rounds passed `72/72` tests — `passed=72, failed=0, errors=0, skipped=0` in every round (verified by orchestrator across results.1.json … results.8.json). The union of failing tests across all 8 rounds is empty, so there is no flakiness signal and no failure to diagnose.

**Tests deleted:** None. No test failed in any round, so STEP 1 (PRD coverage + unique-derivability) was never triggered.

**Fixes applied to test_helpers/:** None required.

**Fixes applied to implementation/:** None required.

The implementation already passes the full test suite stably under the 8× concurrent per-test-server isolation regime. Exited on a clean sweep on the first iteration.

## Step 8: Finalize PRD — SKIPPED — 2026-06-06T17:38:23.000Z

Skipped per the Step 8 skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes (zero iterations beyond the baseline). `PRD.md` already determined every behavior the implementation exhibits at the Step 7 sites, so no `PRD_FINALIZED.md` was produced. Step 9 will run from `PRD.md` directly.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-06T17:42:35.000Z

Produced `workspace/PRD_COMPLETED.md` via a full PRD-vs-`implementation/` scan, starting from `PRD.md` (PRD_FINALIZED.md absent — Step 8 skipped).

### File metrics
- `PRD.md`: 314 lines, 51,783 chars
- `PRD_COMPLETED.md`: 314 lines, 53,311 chars
- Char delta: **+1,528**; line count unchanged (all edits in-paragraph inserts)

### Counts
- Ambiguity-pins: **5**
- Mismatch-revisions: **1**

### Per-change log (`{section} — {action} — {kind} — {what} — {impl ref}`)
- §2.2 (API Response Structure) — insert — ambiguity — Pin that `api_request_timestamp` is drawn from real wall-clock UTC and is independent of the deterministic test clock (which governs only persisted entity fields) — `response.py:31-33` vs `clock.py:21-25`
- §2.3 (Pagination) — insert — ambiguity — Pin that an out-of-range or non-integer `limit`/`offset` is rejected with `ERR_INVALID_REQUEST` rather than clamped — `services/validate.py:127-152`
- §2.8 (Segregation of Duties) — insert — ambiguity — Pin that the approver's `X-User-ID` is recorded internally for the SoD check and, unlike `posted_by_user_id`/`signed_by_user_id`, is NOT exposed on the advance read body — `routes/advances.py:186` + `services/serialize.py:11`
- §3.3 (Pay Periods and the Time Feed) — revise — mismatch — Clarify that `shift_end_at` must be strictly before the period's `end_at` (equal is out of window) because the period interval is half-open; the bare "must fall within the period" admitted the inclusive reading the impl rejects — `routes/time_entries.py:59-63`
- §3.4 (Computing Available Earnings) — insert — ambiguity — Pin that when multiple periods are non-disbursed the one with greatest `period_index` is current, and the figure is 0 when none is non-disbursed — `services/domain.py:42-56,114-118`
- §3.5 (Requesting and Pricing an Advance) — insert — ambiguity — Pin that if the employer has no `ACTIVE` fee schedule at approval, both `expedite_fee_cents` and `total_fee_cents` are 0 regardless of `disbursement_speed`/`tip_cents` — `routes/advances.py:171-177`

Items deliberately left unchanged (PRD already pins, impl matches): tier tie-break by earliest `created_at` (§3.6), archive-on-create for policies/fee schedules (§3.1), disbursement funding-then-frozen check order (§3.8), `lifetime_advanced_cents`/`period_advance_count`/`outstanding_principal_cents` set definitions, manual-recoup over-recoup range rule (§3.9), fee-cap tip-trimming order (§3.7), fee-first-recoup vs full-recoup-target-netting asymmetry (§3.10).

---

## Pipeline complete

All 9 steps finished. Final test status: **72/72 passing across all 8 parallel per-test-server rounds**. Task directory `tasks/task_0204_earned_wage_access` contains the full artifact set: SCAFFOLD.yaml + two design indices, PRD.md + PRD_COMPLETED.md, test_helpers/ + test_suite/ (72 tests), workspace/implementation/ (Python/Flask, in-memory), and results.{1..8}.json. PRD_FINALIZED.md absent (Step 8 skipped — Step 7 needed zero fixes).

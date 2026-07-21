# Worklog — task_1025_model_rc_hobby

## Step 1: Create task directory — 2026-07-15T05:11:39.000Z

Created `tasks/task_1025_model_rc_hobby/` and `tasks/task_1025_model_rc_hobby/workspace/` (pre-assigned folder, no index scan). Verified `prd-bench-local-run` on PATH and `INSTRUCTION.md` present at project root.

## Step 2: Generate scaffold — 2026-07-15T05:39:00.000Z

All consistency checks pass. The scaffold is complete and clean. Here is the summary.

Generated a complete Expert-difficulty scaffold for **task_1025 Model, RC & Hobby Store**. All three files pass `scaffold_lint.py` with **VERDICT: clean lint**. Additionally verified all three parse via `yaml.safe_load`.

**Profile:** quota/allocation × compliance/audit; flat topology (FK-linked peers — the prioritized-for-diversity shape); parallel state-machine shape; hierarchical_override RBAC.

**Contents:**
- **8 entities:** Customer, Product, PreOrderCampaign, PreOrderReservation, Order, ServiceJob, RaceEvent, RaceEntry (9 FKs, all with reverse-reachability GETs).
- **6 state machines** incl. two non-linear: Order (parallel `payment_status × fulfillment_status`) and ServiceJob (cyclic QC→IN_PROGRESS rework loop).
- **7 calculations:** order_totals (tiered discount + hazmat surcharge), loyalty_points (per-line-floor-then-sum + provisional/final dual-variant), loyalty_tier (inclusive threshold), customer_lifetime_spend, service_pricing (quote/invoice dual-variant), campaign_allocation (waterfall + conserved invariant), entry_points.
- **~17 validations** (9 priority layers), **32 endpoints**, **22 errors**, **3 roles** (Customer entity-backed; StoreStaff/StoreManager opaque).
- **1 OCC concurrency rule** (stale-campaign-version on reservation create, 412).

**Design instances:** §1.8 = **18** (2 per each of the 9 difficulty rules, all with pre-computed literal asserts); §1.9 = **26 active corner instances + 5 excluded_because stubs** (49 unique names total).

**Note:** caught and fixed one semantic trap — removed a spurious campaign `FULFILLED` auto-transition that would have made the depth-3 cascade's single-reservation campaign terminal and blocked its cancel. Scope note: scenario's trade-in/consignment and special-order themes intentionally omitted to keep within Expert's 32-endpoint ceiling.

## Step 3: Copy shared files — 2026-07-15T05:40:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1025_model_rc_hobby/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-15T05:47:00.000Z

Generated `workspace/PRD.md` for the Expert-difficulty Model, RC & Hobby Store API. 5 top-level sections; §2 has 9 subsections; §3 has 6 workflow subsections; §4 documents 32 endpoints; §5 lists 22 error codes. All three hard-contract checks (field coverage, rule coverage, §3 path-purity) PASS.

Notable: scaffold declares two named constants with no numeric value — `CHECKIN_WINDOW_LEAD_MINUTES` and `SERVICE_BUFFER_MINUTES`. PRD-gen expressed both as named parameters (direction/inclusivity preserved) without inventing a number. `EXPIRED` (terminal PreOrderReservation enum with no inbound transition) enumerated explicitly in §3.3. Two undeclared cents thresholds embedded with dual cents/dollar phrasing (50,000 cents=$500 SILVER; 200,000 cents=$2,000 GOLD).

## Orchestrator patch: pin SERVICE_BUFFER_MINUTES=30 — 2026-07-15T05:48:00.000Z

Design (`SCAFFOLD_DIFFICULTY_DESIGN.yaml:719`) pins `SERVICE_BUFFER_MINUTES=30`, and difficulty instance `rt_service_bench_buffer_overlap` asserts a 20-min gap → `ERR_BENCH_CONFLICT`. That test is only uniquely-derivable if PRD states the value. Patched `workspace/PRD.md` §2.8 to state "at least 30 minutes (SERVICE_BUFFER_MINUTES)" and the SCAFFOLD's three references to include `(30)`; both re-`safe_load` clean. `CHECKIN_WINDOW_LEAD_MINUTES` left unpinned — every check-in-window test triggers with the clock weeks before the heat, so the exact lead is not boundary-relevant and the tests stay derivable without a value.

## Step 5: Generate unit tests — 2026-07-15T06:05:00.000Z

8 files under `test_suite/` (7 `test_*.py` + `conftest.py`), backed by 9 `test_helpers/` modules. **62 tests, all collect cleanly.** Queue A (Difficulty): 36 tests — all 18 instances (9 rules × 2) with exactly 2 each. Queue B (Corner): 26 tests — all 26 non-stub instances, 1 each. The 5 `cn_stub_*` entries correctly NOT translated. All 73 quoted citations verbatim-verified against PRD.md; exactly one `Design:` tag per test; no skip/xfail; no scaffold leakage.

Instances SKIPPED: None. Coverage nuance: `ce_reservation_convert_requires_campaign_allocating` translated with two positive-path tests only; its convert-before-allocate rejection (`ERR_RESERVATION_NOT_ALLOCATED`) NOT asserted because PRD §2.9's guard order (priority-4 state check `ERR_INVALID_STATE` precedes priority-9 `ERR_RESERVATION_NOT_ALLOCATED`) leaves it non-uniquely-derivable. Left gap, not a weakened test — `ERR_RESERVATION_NOT_ALLOCATED` has no standalone assertion.

## Step 6: Generate implementation — 2026-07-15T06:05:00.000Z

Complete Python + Flask impl in `workspace/implementation/`: `start.sh` (foreground, reads `$PORT` default 10000, binds 0.0.0.0, `exec python3 app.py`), `requirements.txt` (Flask==3.0.3), `app.py` (~1000 lines, single-module: in-memory `Store`, envelope, RBAC/auth, 8 entities, 6 state machines, 7 calculations, 22 errors, **all 32 routes** — verified `grep` route count = 32 matching PRD). `ast.parse` passes; boots cleanly; in-memory dicts only (no disk/SQLite/seed). Smoke-tested end-to-end across every workflow.

Key decisions: `CHECKIN_WINDOW_LEAD_MINUTES` = 60 min (not boundary-relevant); `SERVICE_BUFFER_MINUTES=30` inclusive (exactly-30 accepted). Reservation CONVERT checks `ERR_RESERVATION_NOT_ALLOCATED` (reservation status) before cross-entity campaign-ALLOCATING `ERR_INVALID_STATE` per §3.3 prose. Validation precedence follows §2.9. Logical clock defaults `2026-07-01T00:00:00Z`; `created_at` uses logical clock + insertion-sequence tiebreak for stable allocation sweep ordering.

## Step 7: Run tests and iterate — 2026-07-15T06:20:00.000Z

**All 8 rounds pass 62/62 across both waves (2 waves of 4, via `workspace/sweep.sh`). Clean sweep achieved.** Verified all 8 `results.{1..8}.json` = passed 62 / total 62.

**Iterations run:** 2 (baseline sweep + 1 fix iteration).

**Tests deleted:** None. No PRD-silence or non-unique-derivability issues found.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `test_suite/` (STEP 2 — test-vs-PRD consistency):**
- `test_suite/test_06_race_events.py`, three check-in tests — `test_checkin_safety_error_beats_temporal`, `test_checkin_without_ack_leaves_entry_registered`, `test_checkin_before_window_rejected`. Each called `make_running_event(...)` (create → OPEN → RUN) and *then* `register_entry(...)`. That order violates PRD §3.6: events open for registration (SCHEDULED → OPEN) then set running (OPEN → RUNNING), so registration is only accepted while OPEN. Registering against an already-RUNNING event was correctly rejected by the PRD-faithful impl with `ERR_INVALID_STATE`, failing setup before the check-in under test ran. Fixed each test to `make_open_event(...)` → `register_entry(...)` → transition `RUN` → check-in. Preserves each assertion (safety-beats-temporal precedence, no-ack leaves entry REGISTERED, check-in-window-closed) while constructing a PRD-consistent precondition.

**Fixes applied to `implementation/`:** None — the impl's registration state gate is PRD-grounded and was not the source of failure.

**Key finding:** all 3 failures were consistent (not flaky), shared identical setup error, matching the triage hint (fixture/setup misuse, not an impl bug). `make_running_event` now unused but its import is harmless.

## Step 8: Finalize PRD — 2026-07-15T06:16:00.000Z

Produced `workspace/PRD_FINALIZED.md`. Line counts: PRD.md=236, PRD_FINALIZED.md=236 (~0% delta; one §3.6 line's prose expanded).

**Change (1 bullet):** §3.6 (Race Events, registration) — revise — added explicit event-must-be-`OPEN` state precondition for registration, naming `ERR_INVALID_STATE`, noting the state check precedes the temporal-window check per §2.9 — impl `app.py:1206-1208`.

**Trace:** Step-7 fixes were test-setup ordering bugs (register while OPEN). PRD.md §3.6 pinned only the *temporal* window explicitly and merely implied OPEN via "opened for registration" — a fresh implementer could plausibly allow registration against a RUNNING event whose window is still open (real behavioral fork). Genuine PRD silence the impl pinned. Pre-edit search confirmed the sole registration endpoint `create_race_entry` gates only on `status != "OPEN"`; check-in's separate RUNNING gate untouched; wording enumerates the non-OPEN states and orders state-before-window per §2.9.

## Step 9: Complete PRD — 2026-07-15T06:19:00.000Z

Produced `workspace/PRD_COMPLETED.md` (copied from PRD_FINALIZED.md, then edited). Line count 236→236 (all in-paragraph); char delta 40,638→41,950 = +1,312. **Ambiguity-pins: 4 · Mismatch-revisions: 2** (6 pins across 5 paragraphs).

**Changes:**
- §2.3 Pagination — insert — ambiguity — list ordering ties on identical `created_at` break by creation order (earliest first); impl sorts `(created_at, _seq)` — app.py:305.
- §2.8 Logical Clock/Windows — insert — ambiguity — pinned `CHECKIN_WINDOW_LEAD_MINUTES = 60 minutes`, check-in window as half-open `[heat_start − 60m, heat_end)` — app.py:31,1319-1320.
- §3.3 Allocation sweep — revise — mismatch — `created_at` primary with creation-order tiebreak on equal timestamps (was "only ordering key") — app.py:564.
- §3.3 Reservation CONVERT — revise — mismatch — pinned guard order (reservation-ALLOCATED readiness → campaign-ALLOCATING state → stock), overriding §2.9 ladder (impl returns `ERR_RESERVATION_NOT_ALLOCATED` even when campaign also not ALLOCATING) — app.py:703-710.
- §3.3 Reservation CONVERT — insert — ambiguity — CONVERT action restricted to store personnel — app.py:700.
- §3.5 Service-job SCHEDULE — insert — ambiguity — scheduling records slot without changing `status`, allowed from any non-terminal state, `ERR_INVALID_STATE` only once COMPLETED/CANCELLED — app.py:1006-1007.

Verified already-pinned (no change): logical-clock default 2026-07-01T00:00:00Z; provisional/final per-line-floor-then-sum; hazmat surcharge 500 flat + discount 0/5/10 floor-on-discount surcharge-after-discount; loyalty thresholds 50000/200000 inclusive-lower; bench 30-min inclusive + lane half-open adjacency-allowed; FULFILL tier snapshot; `remaining_units` presence.

---

## Pipeline complete — 2026-07-15T06:19:00.000Z

All 9 steps done. Final state: **62 tests, 8/8 stability rounds pass 62/62.** Artifacts in `tasks/task_1025_model_rc_hobby/`: SCAFFOLD.yaml (+3 design/corner), worklog.md, test_helpers/, test_suite/, workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, sweep.sh, implementation/}.

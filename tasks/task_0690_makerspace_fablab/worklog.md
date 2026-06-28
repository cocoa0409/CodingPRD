# Worklog — task_0690_makerspace_fablab

## Step 1: Create Task Directory — 2026-06-28T09:25:39.000Z

Directory scan SKIPPED per execution directives (parallel-run ID-collision avoidance). Using `tasks/task_0690_makerspace_fablab` verbatim as {task_dir}. Confirmed `tasks/task_0690_makerspace_fablab/` and `tasks/task_0690_makerspace_fablab/workspace/` already exist on disk (empty workspace). INSTRUCTION.md present at project root. `prd-bench-local-run` available at /usr/local/bin/prd-bench-local-run.

## Step 2: Generate Scaffold — 2026-06-28T09:51:00.000Z

Every formula-derived literal verifies. All three scaffold artifacts are complete, internally consistent, lint-clean, and the asserted numbers all check out against the pinned formulas.

Generated three scaffold artifacts for an **Expert**-difficulty Makerspace & Fab-Lab Membership benchmark:
- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys) — 1432 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single `scaffold_difficulty_design` key) — 1167 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` (single `scaffold_corner_design` key) — 1359 lines

**Complexity profile**: primary archetype *temporal_windowing* + secondary *access_control_matrix*; flat topology; parallel state-machine shape; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers.

**Entities (11)**: MembershipTier, Member, Machine, Certification, Reservation, Locker, MaterialItem, MaterialPurchase, Workshop, WorkshopEnrollment, WalletEntry (append-only ledger). 13 FKs, all with reverse-reachability GETs.

**State machines (7)**: Member subscription (linear + SUSPENDED revert), Certification (cyclic ACTIVE↔EXPIRED renewal loop), Reservation (parallel `occupancy_status` × `billing_status`, with CONFIRMED→HELD release revert), Locker, MaterialPurchase, Workshop (branching OPEN↔FULL→RUNNING→COMPLETED/CANCELLED), WorkshopEnrollment (branching ENROLLED→{ATTENDED, NO_SHOW, WITHDRAWN}).

**Calculations (5, 2 with dual variants)**: `session_charge` (forward estimate vs final actual; pinned single-round-after-discount), `material_billing` (nested per-line-then-surcharge rounding order), `membership_proration` (forward full-month vs chronological elapsed-day accrual), `certification_readiness` (weighted score, ≥0.8 gate), `locker_overage` (threshold).

**Validations (14, ordered)** and **errors (20)** including ERR_WAIVER_REQUIRED, ERR_CERTIFICATION_REQUIRED, ERR_READINESS_NOT_MET, ERR_RESERVATION_OVERLAP, ERR_CONVERT_TO_MONTHLY, ERR_STALE_VERSION, etc. **Endpoints (60)** including a `/_clock/set_current_utc` test-driving endpoint defaulting to `2026-04-01T00:00:00Z`. **Roles (3)**: Member (entity_backed), StaffInstructor (entity_backed), FacilityAdmin (opaque). **Concurrency rules (2)**: OCC on Member.version for locker-create and reservation-confirm.

**§1.8**: 9 rule_ids × 2 = **18 instances**. **§1.9**: **36 instances** (31 active + 5 `excluded_because` stubs) across all 9 claim-extraction-guide sections.

**Verification**: `scaffold_lint.py` returns `VERDICT: clean lint`; all three YAML files parse; no forbidden concurrency vocabulary; every grounds ref resolves; all instance names unique; all 15 formula-derived assertion literals recomputed and confirmed against the pinned formulas.

## Step 3: Copy Shared Files — 2026-06-28T09:52:06.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0690_makerspace_fablab/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-28T09:56:00.000Z

Generated `workspace/PRD.md` — a prose PRD for the **Makerspace & Fab-Lab Membership** API (~6,700 words / 314 lines).

### Structure
- **§1 Introduction** — 3 paragraphs covering system goals, the safety/billing tensions, and the logical-clock model.
- **§2 Global Specifications** — 10 domain-derived subsections: RBAC (all three roles; `Member`/`StaffInstructor` entity-backed, `FacilityAdmin` opaque), fixed §2.2 envelope (verbatim, byte-for-byte), Pagination, Common Properties + Logical Clock, Optimistic Concurrency Control, Validation Ordering / Error Precedence, Nested Lookup & FK Resolution, Money/Rounding/Wallet Ledger, Hierarchical Consistency & Cascades, Enumerations/Configuration.
- **§3 Business Logic** — 11 subsections by lifecycle (config → join → day-passes → certifications → booking → confirm/settle → lockers → materials → workshops → member endgame → calculations). No tables, no path/method leaks.
- **§4 Endpoint Definitions** — 4-column table, all 60 endpoints.
- **§5 Error Catalogue** — 2-column table, all 20 error codes.

### Coverage
- **Entities**: all 11, including `WalletEntry` flagged `common_fields: false` (only `id` + `created_at`).
- **State machines**: all 7 with cascades A–D (suspend-cancels-reservations; cert-lapse cancels future unsupervised; bill decrements stock; workshop-complete resolves stragglers + ATTENDED mints certification).
- **Calculations**: all 5 step-for-step with single-rounding placement — `session_charge` (dual variant), `material_billing` (per-line rounding), `membership_proration` (dual variant), `certification_readiness` (0.5/0.2/0.3 weights, gate ≥0.8), `locker_overage` (30¢/L).
- **Concurrency**: both OCC rules (`POST /lockers`, `POST /reservations/{id}/confirm`) with `expected_member_version`, `ERR_STALE_VERSION`, HTTP 412.
- **Validations**: all 14 priority levels as explicit precedence chain.

### Hard Contract reports — all PASS
Field coverage: 77 required / 77 present / 0 missing. Rule coverage: 14 validations + 2 OCC + all transitions/cascades + 5 calculations, 0 missing. Path purity (§3): 446 backtick tokens scanned, 0 path/method leaks. Did NOT open either design YAML.

## Step 5: Generate Unit Tests — 2026-06-28T10:11:00.000Z

**Test helpers (Stage 1) — 9 modules** in `test_helpers/`: `types.py` (11 entity TypedDicts + 12 enums; `WalletEntry` omits `updated_at`/`version`), `api_client.py` (one method per endpoint), `api_errors.py` (`ApiErrorId` enum + HTTP status map), `assertions.py`, `factories.py` (input-only payload factories), `constants.py` (readiness 0.8, overage 30c/L, cycle 30d, daypass cap 3, clock default), `test_users.py` (per-instance member/staff header builders for the two entity_backed roles), `fixtures.py` (composite setup helpers threading real entity ids into ownership-gated headers), `__init__.py`.

**Test suite (Stage 2) — 10 files, 68 test functions** in `test_suite/` (plus `conftest.py`).

**Coverage:** Queue A (Difficulty): **36 tests** — all 18 instances (9 rule_ids × 2) covered by exactly 2 tests each. Queue B (Corner): **32 tests** — all 32 non-stub instances covered by ≥1 test each.

**Skipped instances: 4 — all `excluded_because:` stubs** (reason: stub owned by a difficulty instance, not a PRD gap). All four cross-refs verified to resolve to real difficulty names. No PRD-first filter rejections needed — every non-stub instance had verbatim, uniquely-derivable PRD coverage. One assertion narrowed (`confirm_response_reflects_debit_immediately` asserts immediate-GET wallet rather than a non-existent `wallet_credit_cents` field on the confirm response, keeping it PRD-faithful).

**Verification:** all 68 tests collect under pytest; every docstring carries exactly one `Design:` tag (36 Difficulty + 32 Corner); every quoted PRD citation verbatim; no scaffold refs; no skip/xfail markers; pyflakes-clean.

## Step 6: Generate Implementation — 2026-06-28T10:11:00.000Z

Generated complete Python + Flask implementation in `workspace/implementation/`.

**Files:** `app.py` (single-file Flask, ~1,000 lines — all 60 endpoints, 8 state machines, 5 calculations, validation precedence chain, RBAC, cascades), `start.sh` (`set -euo pipefail`, cd to script dir, guarded pip install, `exec python3 app.py` foreground), `requirements.txt` (flask).

**Key decisions:** single-file layout for fast boot under per-test-server isolation. Storage in-memory only (one `Store` dict per collection, UUID keys), nothing seeded. Logical clock module-level `Clock` defaulting to 2026-04-01T00:00:00Z; `/_clock/set_current_utc` + `POST /members` are the two auth-exempt endpoints. OCC (`expected_member_version`) on exactly `POST /lockers` and `POST /reservations/{id}/confirm` at precedence slot 5; mismatch → `ERR_STALE_VERSION` (412). Money via `decimal.Decimal` + `ROUND_HALF_UP`, rounding placed per §3.11. Envelope matches §2.2 verbatim; auth headers `X-User-ID`/`X-User-Role`.

**PRD ambiguities resolved:** (1) list ordering on identical `created_at` — internal monotonic `_seq` tiebreaker (stripped from output) to preserve insertion order for the append-only wallet ledger; (2) cooldown overlap geometry — dilate both existing and new window end by buffer before half-open comparison (cooldown=0 reduces to bare half-open adjacency); (3) final-charge prepaid reconciliation at check-out — recompute free minutes against pre-confirm prepaid balance and adjust remaining by delta to avoid double-counting.

**Note:** impl-gen reported intermittent host SIGTERM (documented parallel-saturation issue) so it validated envelope/clock via in-process Flask test client; start.sh booted and served HTTP on a fresh process during testing.

## Step 7: Run Tests and Iterate — 2026-06-28T10:24:00.000Z

Clean 8-round parallel sweep achieved: all 8 rounds passed 68/68.

**Iterations run:** 2 (initial sweep to surface failures; one fix iteration; confirming sweep).

**Tests deleted:** None. Both failing tests were PRD-covered and uniquely derivable (PRD §3.5 cooldown dilation + PRD §3.6 confirm-time overlap → `ERR_RESERVATION_OVERLAP`); the assertions were faithful — only the construction order was wrong.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `test_suite/`:**
- `test_07_overlap_geometry.py`, both `test_confirm_within_cooldown_buffer_rejected` and `test_cooldown_overlap_leaves_second_reservation_held`: reordered the setup to create reservation B (11:10-12:00) **before** reservation A (10:00-11:00). The original order created A first, so B's *creation* collided with A's dilated window [10:00,11:15) and failed at setup before the test could ever reach the confirm-time check. PRD §3.5 dilation is one-sided ("a new booking must leave the buffer **after** any neighbor"), so creating B first lets it reach a HELD state, then confirming B is correctly rejected against A's dilated window — exactly the assertion under test. Assertions unchanged.

**Fixes applied to `implementation/`:**
- `app.py`, `_intervals_overlap`: removed the symmetric `new_end_dilated` dilation. The implementation was dilating *both* the existing window's end and the new window's end, which is stricter than PRD §3.5 (which dilates only the **existing** window's end so the buffer is required only *after* a neighbor, not before). This extra buffer is not traceable to any PRD sentence and would have wrongly rejected the B-before-A creation. The change is strictly more permissive, so no previously-passing overlap/precedence test was affected.

**Two failure modes were intertwined:** a test-bug (ordering) masked by an implementation-bug (over-strict symmetric dilation). Both had to be corrected together — fixing only the test ordering would still have failed against the symmetric-dilation implementation.

**Final sweep confirmation:** all 8 parallel rounds passed == total, 68/68 each, 0 failed, 0 errors. (Orchestrator independently re-ran the 8-round sweep with the verbatim `cd ... && bash start.sh` start-command after the subagent exited; the subagent's `results.*.json` had been cleaned up. Re-run produced fresh `results.{1..8}.json` all showing 68/68/0/0.)

## Step 8: Finalize PRD — 2026-06-28T10:26:49.000Z

Step 8 ran (NOT skipped — Step 7 had 1 implementation fix + 2 test_suite fixes). Result: **PRD_FINALIZED.md is an exact copy of PRD.md (314 vs 314 lines, 0% delta, 0 edits)** — `diff -q` confirms IDENTICAL.

**Per-item analysis of Step 7 diff:**
1. Test fixture reordering (create reservation B before A) — pure setup-ordering bug exercising PRD §3.5's one-sided dilation; reveals no PRD under-determination. No PRD edit.
2. Impl fix: removed symmetric `new_end` dilation in `_intervals_overlap` (app.py:994-1002) — an implementation bug corrected to *match* PRD §3.5 as already written ("each **existing** window is dilated"; "mandatory post-session cooldown"; "a new booking must leave the buffer **after** any neighbor"). A fresh implementer reading PRD §3.5 alone produces the surviving one-sided behavior. No PRD edit.
3. Confirm-time overlap → `ERR_RESERVATION_OVERLAP` — already pinned in PRD §3.6 and §3.5 ("At both reservation creation and reservation confirm..."). No PRD edit.

**Pre-edit NO-NEW-MISMATCH enumeration** (performed even though no edit committed): subject = reservation overlap/cooldown geometry; enumerated `cooldown_minutes` config (app.py:822,833 default 0), `_intervals_overlap` (994-1002), `_check_overlap` (1005-1017), both callsites creation (1042) + confirm (1140) — all use identical one-sided geometry, no divergent overlap logic. Existing §3.5/§3.6 prose consistent with all paths; no edit needed.

## Step 9: Complete PRD — 2026-06-28T10:30:52.000Z

Step 9 ran (always runs). Produced **PRD_COMPLETED.md** from base PRD_FINALIZED.md: 314→314 lines, 47,109→48,745 chars (+1,636), 5 changed lines.

**Counts:** 5 changes total — **2 mismatch-revisions, 3 ambiguity-pins.**

**Per-change bullets:**
- §3.3 Day-Passes — revise — mismatch — PRD framed `daypass_count_window` as a true trailing-30-day rolling window; impl maintains it as a monotonic counter that only resets to 0 on a FacilityAdmin cycle-roll (never decayed by clock advance). Also pinned buy-daypass has no waiver/status/tier-mode/funds precondition and debits unconditionally (wallet may go negative) — app.py:760-773 (buy_daypass), :776-785 (roll_cycle), :470-472 (debit_wallet).
- §3.5 Overlap geometry — revise — mismatch — PRD's "each existing window is dilated" left dilation side ambiguous; impl dilates only the existing window's `end_at` (one-sided post-session buffer), `start_at` unchanged — app.py:994-1002 (_intervals_overlap).
- §3.6 Checking out — insert — ambiguity — PRD silent on free-minute handling at check-out; impl re-derives `free_minutes_applied` against `actual_minutes` (prepaid restored to pre-confirm level) and reconciles `prepaid_minutes_remaining` by the difference — app.py:1214-1227 (check_out).
- §3.2 Top-up — insert — ambiguity — PRD didn't constrain `amount_cents`; impl rejects missing/non-integer/zero/negative with `ERR_INVALID_REQUEST` (422) — app.py:660-662 (topup).
- §3.4 Readiness recompute — insert — ambiguity — PRD listed recompute on created/renewed/expiry but omitted revoke; impl also recomputes on revoke (dropping the 0.5 ACTIVE component) — app.py:974 (revoke_certification), :936 (refresh_expiry).

**Deliberately left unchanged** (already pinned or covered by explicit catch-all): clock field names (§2.4); §2.6 error precedence chain; list-filter params beyond those PRD names (§2.7 "and so on"); reservation default field shape; §2.8 "balance can never go negative" framing (already qualified by its own three-checkpoint funds-check list excluding day-passes/overage — the new §3.3 note is the more specific pin).

---

## PIPELINE COMPLETE — 2026-06-28T10:30:52.000Z

All 9 steps ran to completion. `workspace/PRD_COMPLETED.md` exists on disk. Final 8-round stability sweep: all 8 rounds 68/68 passed, 0 failed, 0 errors (`results.{1..8}.json` present in workspace/implementation/).

# Worklog — task_0252_parks_recreation_facility_reservation

## Step 1: Create task directory — 2026-06-08T00:00:00.000Z

Created `tasks/task_0252_parks_recreation_facility_reservation/` and its `workspace/` subdirectory (pre-allocated path; no ID auto-scan). Verified `INSTRUCTION.md` exists at project root.

## Step 2: Generate scaffold (Expert band) — 2026-06-08T00:00:00.000Z

All three required files written and the linter verdict is clean. The scaffold generation is complete. (SCAFFOLD.yaml 1210 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1009 lines, SCAFFOLD_CORNER_DESIGN.yaml 1203 lines.)

Generated all three Expert-band scaffold artifacts. `scaffold_lint.py` reports **VERDICT: clean lint** (345 calls scanned across §1.8+§1.9, all FKs reverse-reachable). Did not look at any sibling task.

**Archetype:** temporal_windowing (primary) + quota_allocation (secondary, prime-slot lottery); branching state-machine shape; hybrid topology; peer_roles; immediate consistency. Layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, scheduled_actions.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **9 entities:** Patron, Facility, InsuranceCertificate (COI), LeagueSeries, Permit, Payment, Refund, LotteryRound, LotteryEntry. Cross-aggregate FKs (Permit references 5 entities); all FKs reverse-reachable via filtered-list GETs (api_prefix `/` for flat collections).
- **5 state machines:** Permit (branching fork: APPLIED→{GRANTED,WAITLISTED,DENIED}, WAITLISTED→GRANTED rejoin, +COMPLETED/NO_SHOW/CANCELLED), LeagueSeries (compound bubble-up + cascade cancel), LotteryRound (OPEN→{DRAWN,CANCELLED}), LotteryEntry (ENTERED→{WON,LOST,WITHDRAWN}), InsuranceCertificate (ACTIVE→{EXPIRED,REVOKED}).
- **2 concurrency rules:** OCC on Facility.version for permit-grant and lottery-draw (both 412 ERR_STALE_VERSION).
- **6 calculations:** prime_overlap_hours (interval_merge), provisional_quote_fee (forward-looking, round-per-component-then-sum) vs final_grant_fee (chronological, sum-then-round, residency re-resolved) — the dual-variant divergence (5500 vs 5499); cancellation_refund (two-factor tiered: fee tier × deposit-forfeit cutoff); patron_standing (threshold); lottery_selection (weighted_scoring, deterministic by priority_weight then entry_seq — no random id in decisions).
- **15 validations** (priority-ordered: auth→ownership→state→OCC→barred→COI→window→double-booking→probation-prime→lottery→duplicate→payment), **18 errors**, **47 endpoints** (incl. `/_clock/set_current_utc`, `/_ops/sweep`, `/_inject/no_show_strikes` test-driving), **3 roles** (RecCoordinator opaque, Patron entity_backed, FinanceClerk opaque).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 9 rule_ids × 2 = **18 instances**, all with executable empty-DB setup chains and code-computed literal asserts (fees/refunds precomputed in Python). Each rule's two instances span different entity domains / error-category pairs / interval semantics / conserved quantities per §0.5 differentiation clauses.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **39 instances** (36 active + 3 `excluded_because` stubs) across all 9 taxonomy sections — CRUD/defaults/computed-fields, invalid-transition/terminal-lockdown/idempotency/bubble-up, residency-flip variant selection, every remaining error trigger (validation, COI-insufficient/required, probation-prime, lottery-not-closed, duplicate-entry, invalid-window, payment-required), RBAC denials (unauthenticated/forbidden/not-owner), OCC happy-path + stale-version, scheduled clock-gating, immediate consistency. All names unique across both design files; all stub references resolve.

Key design note: the WAITLIST grant outcome explicitly short-circuits before COI/payment gates (validation priority 11 & 15 annotated) to keep the branching state machine's fixtures consistent.

## Step 3: Copy INSTRUCTION.md — 2026-06-08T00:00:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-08T00:00:00.000Z

PRD.md generated (289 lines, 45KB). All hard-contract reports PASS.

**Task:** PRD for `parks-rec-reservation` (Parks & Recreation Facility Reservation, Expert band).

**Sections covered:**
- §1 Introduction — 3-paragraph framing of the municipal allocation problem (residency tiers, leagues, COI, prime-slot lottery, OCC race).
- §2 Global Specs — 8 subsections: 2.1 RBAC (3 roles with identity translation: `Patron` entity-backed, `RecCoordinator`/`FinanceClerk` opaque), 2.2 verbatim envelope, 2.3 pagination, 2.4 common properties (all 9 entities carry full `common_fields`), 2.5 hierarchical consistency / derived counts, 2.6 facility OCC, 2.7 monetary precision, 2.8 nested retrieval + `ERR_VALIDATION`.
- §3 Business Logic — 10 lifecycle-organized subsections (patrons/standing, facilities/pricing, application/quote, payments/refund ledger, grant-waitlist-deny, final-fee divergence, cancel/complete/no-show/tiered refunds, league cascade, lottery, COI/ops-sweep).
- §4 — 47-endpoint table (4 columns); §5 — 18-error table (2 columns).

**Counts conveyed:** 9 entities, 47 endpoints, 18 error codes, 6 calculations, 15 priority-ordered validations, 4 state machines, 2 concurrency rules.

**Notable scattering decisions:**
- Grant endpoint params split: `expected_facility_version`/`on_conflict` introduced in §3.5, while OCC mechanics live in §2.6 and `final_fee_cents` derivation in §3.6.
- The dual-variant pricing divergence (round-per-component-then-sum for `quoted_fee_cents` vs. sum-then-round for `final_fee_cents`) is stated as a pinned ordering in both §2.7 and §3.6 for reinforcement.
- Validation priority order rendered explicitly as a numbered evaluation sequence in §3.5 (role → existence → state → OCC → barred → double-booking → probation-prime → COI → payment), including the `on_conflict=WAITLIST` short-circuit that skips priority-8/9/15 gates.
- Refund constants (168/48/24h tiers, FORFEIT) embedded as "seven days / two days / one day" prose with inclusive-boundary language; standing thresholds (2/4 strikes) as "at least" comparisons.
- Cascade side-effects (league-cancel → child permit cancels → per-child refund + facility count/version bumps) and lottery-draw permit synthesis stated transitively.

## Step 5: Generate unit tests — 2026-06-08T00:00:00.000Z

Test infrastructure generation complete for task_0252 (Parks & Recreation Facility Reservation, Expert band).

**Stage 1 — `test_helpers/` (9 files written):**
- `types.py` — 10 status/role enums + 9 entity TypedDicts (all carry common_fields: id/created_at/updated_at/version, per PRD §2.4 "All nine resource types … carry the full set").
- `api_client.py` — `ApiClient(GenericApiClient)` with 51 endpoint methods (one per PRD §4 row, incl. `/_clock`, `/_ops/sweep`, `/_inject`).
- `api_errors.py` — 18-error `ApiErrorId` enum + HTTP status map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions + refund-total invariant.
- `factories.py` — input-only payload factories (auto-unique patron emails; optional facility fields omitted so server defaults apply).
- `constants.py` — refund-lead/standing/lottery-weight/pagination thresholds.
- `test_users.py` — opaque `RecCoordinator`/`FinanceClerk` shared constants + `make_patron_headers(id)` builder for the entity_backed Patron (identity threading).
- `fixtures.py` — composite helpers: `setup_granted_permit`, `setup_applied_permit`, `setup_league_with_children`, `setup_lottery_round_with_entries`, plus primitives (clock/facility/patron/COI/apply/payment/grant/cancel/refund-read).
- `__init__.py` — barrel export.

**Stage 2 — `test_suite/` (conftest + 8 test files, 72 tests):**
- **Queue A (Difficulty):** 36 tests — every one of the 18 instances (9 rules × 2) covered by exactly 2 tests. Second-pass tests use genuinely distinct scenarios (different rate configs, boundary X−1 vs X, alternate overlap geometry, alternate terminal branch).
- **Queue B (Corner):** 36 tests — all 36 non-stub instances covered ≥1. The 3 `excluded_because` stubs (`deny_voids_payment_via_difficulty`, `error_double_booking_via_difficulty`, `cascade_league_cancel_via_difficulty`) were verified to cross-reference real §1.8 instances and were NOT translated.

**Skips:** None. Every non-stub instance passed the PRD-first two-condition filter.

**Audits passed:** All 118 docstring PRD citations are verbatim substrings of PRD.md. Every test has exactly one `Design:` tag pointing to a real instance; no untagged/dual-tagged tests; no `skip`/`xfail`. All files compile; pytest collects 72 tests cleanly.

One internal inconsistency in the difficulty YAML worked around faithfully: `ppvc_barred_before_coi_required`'s setup injects 4 strikes before applying (which PRD §3.3 would block on apply), so the test applies while GOOD then bars before grant — preserving the instance's asserted outcome (ERR_PATRON_BARRED precedes ERR_COI_REQUIRED at grant).

## Step 6: Generate implementation — 2026-06-08T00:00:00.000Z

Implementation complete and verified (boots cleanly from fresh process; store empty, no seeding; <1s ready; binds 0.0.0.0:$PORT default 10000).

**Stack:** Python 3 + Flask 3.0.3, in-memory store, `start.sh` with guarded pip install + `exec python3 app.py`.

**Modules created (22 files):** `app.py`, `clock.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`, `helpers.py`, `serializers.py`, `services/calculations.py`, `services/domain.py`, `routes/` (patrons, facilities, insurance, permits, payments, leagues, lottery, ops).

**Endpoints:** all 49 from the endpoint table implemented, incl. 9 reverse-reachability list endpoints + 3 test-driving endpoints (`/_clock/set_current_utc`, `/_ops/sweep`, `/_inject/no_show_strikes`).

**State machines encoded:** Permit, LeagueSeries (bubble-up + cascade cancel), LotteryRound, LotteryEntry, InsuranceCertificate.

**Calculations encoded:** prime/non-prime hour split; dual-variant pricing (provisional round-per-component-then-sum vs final sum-then-round-once, residency re-resolved at grant — verified deliberate 1-cent divergence 334 vs 333); tiered cancellation refund (168h full / 48h half / <48h none fee, <24h deposit forfeit); patron standing thresholds (2→PROBATION, 4→BARRED); deterministic lottery selection (max weight, tie-break lowest entry_seq). OCC on `Facility.version` via `expected_facility_version` (412 ERR_STALE_VERSION) on grant/draw/facility-PATCH.

**PRD ambiguities resolved:**
1. League PARTIALLY_GRANTED trigger — followed §3.8 precise derivation (`0 < granted < occurrences AND conflicted > 0`); a series with conflicts but zero grants stays PENDING; roll-up recomputed from child states on every child transition.
2. Facility CLOSED check placement — on GRANTED branch after conflict/waitlist fork, ERR_INVALID_STATE; WAITLIST short-circuit on a closed facility unaffected.
3. WAITLISTED child in league cascade cancel — moved straight to CANCELLED with no refund (no deposit/fee held).
4. refund-preview shape — non-persisted Refund-shaped object with `id: null`, `version: 0`, computed at preview-time clock.

Tested end-to-end across 5 scenario batches (71 assertions, all passing).

## Step 7: Run tests and iterate (8-round parallel sweep) — 2026-06-08T17:53:29.000Z

All 8 parallel rounds pass cleanly at 72/72. The loop is complete.

## Summary

**Iterations run:** 2 (initial sweep + 1 fix sweep).

**Initial state:** All 8 rounds consistently 71/72, with a single deterministic failure (not flaky): `test_residency_verified_between_apply_and_grant_changes_final_fee` in `test_suite/test_01_pricing_and_refund_calculations.py`.

**Diagnosis:** The test applies as a RESIDENT-but-unverified patron (so `pricing_residency` is correctly locked to `NON_RESIDENT` at application time per PRD §3.3), verifies residency, then grants. The final fee correctly re-resolved to the RESIDENT tier (`final_fee_cents == 24000` — that assertion passed). The failing assertion was line 208, `granted["pricing_residency"] == "RESIDENT"`. This contradicts the PRD: §3.3 says `pricing_residency` "resolves to RESIDENT only when... `residency_verified` is true **at application time**", and §3.6 explicitly states the grant-moment snapshot "can differ from the one **locked into `pricing_residency`**." So `pricing_residency` must stay `NON_RESIDENT`; only `final_fee_cents` re-resolves. The implementation (`routes/permits.py` grant path) correctly leaves `pricing_residency` untouched and only updates `final_fee_cents`. This was a TEST BUG (STEP 2), not an implementation bug.

**Tests deleted:** None (all 72 trace to verbatim PRD prose and are uniquely derivable).

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `test_suite/`:**
- `test_01_pricing_and_refund_calculations.py`, `test_residency_verified_between_apply_and_grant_changes_final_fee`: corrected the final assertion from `pricing_residency == "RESIDENT"` to `== "NON_RESIDENT"` (made the test more faithful to PRD §3.3/§3.6 — the lock is taken at apply time when the patron was unverified; grant re-resolution drives only `final_fee_cents`). The load-bearing `final_fee_cents == 24000` assertion is preserved unchanged.

**Fixes applied to `implementation/`:** None (implementation was already PRD-faithful).

**Final sweep status:** All 8 parallel rounds passed == total at **72/72**.

## Step 8: Finalize PRD — SKIPPED — 2026-06-08T17:53:29.000Z

Skipped. Step 7 had **0 `implementation/` fixes**, **0 deletions**, **0 `test_helpers/` fixes**, and its single `test_suite/` change was a pure test-bug correction (an assertion mis-translating PRD §3.3/§3.6, which already uniquely determine that `pricing_residency` locks at apply time while only `final_fee_cents` re-resolves at grant). No PRD-silence or PRD/impl mismatch was surfaced for Step 8 to align — `PRD_FINALIZED.md` would be byte-identical to `PRD.md`. Per the resume gate (generate `PRD_FINALIZED.md` only if Step 7 produced implementation fixes), Step 8 is skipped; the always-run Step 9 full PRD-vs-implementation scan (starting from `PRD.md`) subsumes any residual alignment work.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-09T02:00:00.000Z

Step 9 ran to completion and produced `workspace/PRD_COMPLETED.md` (source = `PRD.md`, since Step 8 was skipped). The orchestrating `claude -p` process was terminated by signal (exit 144) immediately after the Step 9 subagent wrote `PRD_COMPLETED.md` but before this worklog entry was appended; the subagent's own summary text was lost with the killed process. This entry is reconstructed by the parent orchestrator from the verifiable on-disk artifact.

Verified facts:
- `PRD_COMPLETED.md` is well-formed and ends correctly (error-code table intact).
- vs `PRD.md`: 289 → 289 lines, +2626 chars, **10 in-paragraph edits** (no new sections/paragraphs).
- Edits pin behaviors the impl exhibits that PRD.md left ambiguous: the double-booking `WAITLIST` short-circuit ordering (evaluated before the facility-open check; insurance/payment gates skipped on the WAITLISTED branch), the facility-open `ERR_INVALID_STATE` gate placement, the `GRANTED`-branch ordering of probation/COI/payment gates (`ERR_PROBATION_PRIME_BLOCKED`, `ERR_COI_REQUIRED`/`ERR_COI_INSUFFICIENT`, combined fee+deposit `ERR_PAYMENT_REQUIRED`), denial full-reversal (VOID payment, no Refund, `refunded_cents`=0), tiered cancellation refund (168h/48h/24h inclusive-low boundaries, deposit forfeiture under 24h, `refund_destination` default `ORIGINAL`), completion deposit release, league-series child generation and roll-up rules (`PENDING`/`PARTIALLY_GRANTED`/`GRANTED`), league-cancel cascade ordering, deterministic lottery winner selection (highest `priority_weight`, tie → lowest `entry_seq`) and synthesized-permit fields, round-cancel `entry_count` retention, and the COI ops-sweep counts (`expired_coi_count`/`recomputed_patron_count`) plus clock-advance `current_utc`.

Sweep status unchanged from Step 7: all 8 parallel rounds 72/72. Task directory is complete through Step 9.

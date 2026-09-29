# Worklog — task_2415_draft_combine_operations

## Step 1: Create task directory — 2026-09-02T15:40:24.337Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2415_draft_combine_operations` and `.../workspace`. Index pre-assigned by the orchestrator invocation (2415); no scan of ./tasks/ performed, no auto-allocation.

## Step 2: Generate scaffold — 2026-09-02T17:56:11.600Z

All three artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_2415_draft_combine_operations/` and pass the generator's lint plus a structural self-check.

**`SCAFFOLD.yaml`** (§1.0–§1.7 only; top-level keys are `scenario`, `domain_name`, `api_prefix`, `complexity_profile`, `response_envelope`, `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`, `endpoints`, `errors`, `roles` — no design keys)
- 13 entities, 9 state machines, 2 §1.2.1 concurrency rules, 9 calculations, 40 ordered validations (priorities 1–40 mapping 1:1 to the 40 error ids), 55 endpoints, 40 errors, 6 roles.

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — single key `scaffold_difficulty_design`: 9 rule blocks, 25 instances (dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 3, compensating_invariant 3).

**`SCAFFOLD_CORNER_DESIGN.yaml`** — single key `scaffold_corner_design`: 9 sections, 96 instances = 70 executable recipes + 26 `excluded_because` stubs. Section split: entities 12, state_machines 11, calculations 14, validations 11, endpoints 6, errors 27, rbac 7, cross_cutting_complexity_layers 7, consistency_model 1.

Verification: `scaffold_lint.py` → `VERDICT: clean lint` (1246 calls scanned across §1.8+§1.9, all conform to §1.5; all 13 entities' FKs reverse-reachable). 121 instance names unique across both design files; all 26 stubs cite real §1.8 instance names and none carries a `test_recipe`; all 40 error codes have at least one trigger.

Design adjudications
- Added `"last_actor_club_id?"` to `GET /draft-ops/pick-trades` input — it was the only FK without reverse-reachability in §1.5.
- Fresh triggers (not stubs) authored for ERR_CYCLE_FROZEN, ERR_ALREADY_DECLARED, ERR_NO_TIMEOUTS_REMAINING, ERR_TRADE_VALUE_IMBALANCED and ERR_CROSS_CYCLE_REFERENCE, because §1.8 only asserts those as outranked or negated conditions, which would not prove triggerability.
- Pagination asserted under `response.meta.total_count/has_more/limit/offset` (SKILL.md declares `pagination_fields` but not their location); every listing instance also asserts `response.data[...]` contents so the test stays meaningful either way.
- Pinned two constants that were referenced but never valued in `SCAFFOLD.yaml`: `ELIGIBILITY_MIN_SEASONS (3)` (entity field description + `Prospect UNREVIEWED→ELIGIBLE` precondition) and `BOOKING_CHECKIN_LEAD_MINUTES (30)` (`CombineBooking SCHEDULED→CHECKED_IN` precondition), matching the existing `PROSPECT_TRAVEL_GAP_MINUTES (10)` style. Without values the guards were unimplementable and the corresponding corner tests unanchored.
- Rewrote three `DraftCycle.version` assertions to be relative to a version captured immediately before the trigger (`== ${cyc_v} + 1` / `== ${cyc_v}`) instead of literal 2/3/1. The literals silently assumed that creating child clubs never bumps the parent's version, which the scaffold does not state; the relative form tests the declared "increments version by 1" side effect directly.
- OCC instances use `expected_prospect_version` / `expected_medical_evaluation_version` sourced from captured `${vars}` rather than literals, per lint check (e).

## Step 3: Copy shared files — 2026-09-02T17:56:11.600Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T18:12:08.935Z

PRD complete.

**Output:** `workspace/PRD.md` — **522 lines** (orchestrator recount: 521), last section **`## 5. Error Code Catalogue`**, ending on the final table row `| \`ERR_UDFA_POOL_EXHAUSTED\` | 422 |` (complete table, real section boundary, no truncation).

**Section list**
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control; 2.2 API Response Structure; 2.3 Pagination; 2.4 Deterministic Guard Ordering; 2.5 The Logical Clock and Temporal Windows; 2.6 Record Identity, Audit Fields and Version Semantics; 2.7 Points, Cents and Rounding Discipline; 2.8 Stale-Parent Rejection on Shares and Contract Offers; 2.9 Left-to-Right Path Resolution and Cycle Cohesion; 2.10 Separation of Duties and Confidentiality Tiering; 2.11 Cascade and Recomputation Discipline
- `## 3. Business Logic & Workflows` — 3.1 Standing Up a Cycle: Registration, Facilities and the Phase Ladder; 3.2 Declaration, Eligibility Determination, and the Waiver Review Loop; 3.3 Combine Invitations and Scheduling the Compressed Week; 3.4 Medical Findings, Consent, and Record Sharing; 3.5 Building the Draft Order: Lottery, Seeding, Forfeits and Compensatory Awards; 3.6 Trading Picks: Chart Valuation, Negotiation Rounds and Conditional Obligations; 3.7 Running the Selection Clock; 3.8 Contract Slotting, the Rookie Pool and the Undrafted Free Agent Window
- `## 4. API Endpoint Definitions` — 55 rows, exactly 4 columns
- `## 5. Error Code Catalogue` — 40 rows, exactly 2 columns

**Hard Contract reports (summary only, never written into PRD.md)**

- **Contract 1 — Field-Name Coverage: PASS.** Two mechanical passes over SCAFFOLD.yaml. Pass 1 (142 entity field names + endpoint identifiers, strict-ident filter) = 150 required, 0 missing. Pass 2 (corrected for the `name?` optional-suffix form plus `{id}` path params) = 156 required, 0 missing. Every entity field name and every endpoint input/query/path identifier appears verbatim in backticks.
- **Contract 2 — Rule Coverage: PASS.** All 40 validations appear as an explicit priority-ordered numbered list in §2.4 with error ID, HTTP status and `applies_to` scope (count verified: 40 numbered items = 40 scaffold validations). Both `concurrency_rules` are documented in §2.8 with write endpoint, `occ_field`, `ERR_STALE_PARENT_VERSION` and 412. All 40 error IDs appear in §1–§4 prose, not only in the §5 table (verified: 0 missing). All 9 state machines' state values appear in prose (0 missing across 75 transitions' source/target states), with sibling-branch symmetry spelled out for the asymmetric pairs (both `DECLARE_INELIGIBLE` branches, all three trade terminations, both selection paths from `PASSED`/`PENDING`, both conditional-tier resolutions, both contract void paths). All 9 calculations are prosed step-for-step including the pinned orderings (per-year rounding before escalation, per-year bonus proration before multiply-back, UDFA tier keyed on base pool pre-credit) and every scaffold constant table (chart bases, decay 0.94, tolerance 0.15, tiers 1200.0/900.0, round bases/decrements, minimum 79,500,000, escalator 4.25 percent, bonus shares, clock minutes, caps 4/8, qualify 250.00, 75/3-day window, UDFA 40,000,000 / 0.10 / 120,000,000 / 60,000,000 / 0.25-0.40-0.55 / seventy-two hours). All endpoint side effects are narrated in §3.
- **Contract 3 — §3 Path Purity: PASS.** 343 distinct backticked tokens in §3; 0 start with `/`, 0 are bare HTTP methods, 0 combine method+path. Zero raw occurrences of `/draft-ops` in §3 (the 7 `_clock` hits are all `on_clock_started_at` / `on_clock_pick_id` field names).

Also verified: §2.2 matches `section-2.2-response-structure.md` byte-for-byte; no fuzzy words (`approximately`, `roughly`, `conservatively`, `about`, `e.g.`, `etc.`) and no pseudocode anywhere in the document.

**Constraints honoured:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped or referenced; no sibling task under `tasks/` was read.

**Orchestrator anti-truncation check:** `tail -12 PRD.md` confirms the file ends on the last row of the §5 error table; `grep '^## '` shows all five top-level sections present. Not truncated; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-02T19:10:51.500Z

All audits pass. Final state verified.

## What was written

**Stage 1 — `test_helpers/`** (9 files)
`__init__.py` (barrel, 243 exports), `types.py` (13 entity TypedDicts + ~25 status Literals), `constants.py` (all PRD-pinned formula constants and canonical instants), `api_errors.py` (40 `ERR_*` ids + `HTTP_STATUS_CODES`, calls `set_error_http_status_map` at import), `api_client.py` (`ApiClient` with one method per the 55 declared endpoints), `factories.py` (30 payload builders), `assertions.py` (common-field + 3 precision families + pick-ledger lookups), `test_users.py` (opaque operator ids + entity-backed header builders), `fixtures.py` (~70 state builders + 22 pytest fixtures).

**Stage 2 — `test_suite/`** — `conftest.py` + 18 numbered test modules (`test_01` … `test_18`).

## Test counts

- **144 test functions** (148 collected node ids; two functions are `parametrize`d with 2 and 4 cases).
- **Queue A (Difficulty): 72 tests** across `test_01`–`test_09`, covering **all 25** difficulty instances with **>=2 tests each**. None skipped.
- **Queue B (Corner): 72 tests** across `test_10`–`test_18`, covering **all 70 LIVE** corner instances with **>=1 test each**. None skipped.

## Instances skipped

Only the **26 `excluded_because:` stubs**, which are not translatable by contract: 7 `calculations`, 5 `validations`, 10 `errors`, 3 `cross_cutting`, 1 `state_machines`. All 26 stub `difficulty_instance:` cross-references were verified to resolve to real queue-A instance names (26/26). No live instance was dropped, and no test is marked `skip`/`xfail` (grep confirms zero occurrences).

## Audit results (`/tmp/audit_2415.py`, AST-based)

- Exactly one `Design:` line per test, and it is the final docstring line: **144/144 pass**.
- Every tag resolves against the design indices; **zero** unresolved tags, **zero** tags pointing at a stub, **zero** dual-tagged or untagged tests.
- Verbatim PRD citation (>=9-word contiguous substring present in `workspace/PRD.md`): **144/144 pass**.
- Coverage-gap report: **none**.
- Total problems reported: **0**.
- Whole-suite `pytest --collect-only -q`: **148 tests collected, 0 errors**.
- Barrel completeness: fixed a gap where `ERR_WAIVER_ROUNDS_EXHAUSTED` was defined in `api_errors.py` but missing from `__init__.py`; a programmatic sweep now shows **zero** error ids missing from the barrel.
- No test or helper references anything under `workspace/implementation/` (grep confirms), and no sibling task was read.

## Notes worth flagging

- Three PRD-derivability judgements caused deliberately narrowed assertions rather than skips: draft-completion assertions avoid pinning *which* advance completes the draft (`lapsed_count`/`on_clock_pick_id` only); `disclosure_state == SEALED` is not asserted after a clock-expiry sweep because the PRD seals only on REVOKE (the test asserts `active_share_count == 0` + `EXPIRED` + `effective_access NONE`); one design-supplied `passed_count == 0` was omitted for the same reason.
- Three `fixtures.py` limitations were composed around locally rather than by editing the frozen helpers: `build_order_final` hardcodes a two-entry lottery sequence, club seed overrides are unreachable through composite builders, and `build_granted_share` hardcodes `consent_expires_at="2027-03-15T12:00:00.000Z"` (which would expire a share before draft day, so late-cycle share tests set a later expiry inline).
- One design figure was independently re-derived after a hand-computation mismatch (HAR UDFA pool): `Decimal`/`ROUND_HALF_UP` confirms the design's `223969910`; no discrepancy.

## Step 6: Generate implementation — 2026-09-02T19:10:51.500Z

Implementation is complete and verified end-to-end.

## Files written
`workspace/implementation/`

**Launcher / infra** — `start.sh` (executable; guarded `pip install -r requirements.txt`, then `exec python3 app.py`), `requirements.txt` (`Flask>=2.2`), `app.py` (app factory, `PORT` default **10000**, per-request `RLock`, `ApiError`/`HTTPException`/catch-all handlers).

**Core modules** — `db.py` (13 in-memory dicts + logical clock, `DEFAULT_CLOCK = 2026-08-01T00:00:00Z`), `constants.py`, `errors.py` (40 error ids -> HTTP), `timeutil.py`, `calc.py` (Decimal/ROUND_HALF_UP: chart values, slotting, comp scores, clock minutes, UDFA pool), `derive.py` (all read-time derived fields), `serialize.py` (13 serializers), `response.py` + `respond.py` (envelope + version settling at handler exit), `auth.py`, `validate.py`, `versioning.py` (fingerprint diffing -> `version` bumps), `logic.py` (shared guards, lottery, order mint, clock cascade, trade valuation, consent cascade).

**Routes** — `routes/__init__.py` plus `cycles, clubs, prospects, waivers, facilities, bookings, medical, picks, trades, claims, contracts, clock` (11 blueprints under `/draft-ops`, `clock` at root).

## Endpoint count
**55** registered rules (`app.url_map`), matching the PRD §4 table path-for-path and method-for-method. All 40 error ids and their HTTP codes were programmatically diffed against the PRD error table: exact match, no extras, no gaps.

## Verification
Two smoke suites (~230 assertions) both finish with **0 failures** against a fresh `start.sh` process: full cycle ladder SETUP->CLOSED, lottery/order mint (incl. compensatory banding and `overall_number` tail placement), pinned slotting arithmetic (round 1 pick 1 = `511476212 / 306885727 / 196721432 / 818361940`), chart decay, trade propose/counter x2/rounds-exhausted/accept/rescind/withdraw/reject/conditional resolution, forfeit + capital tier, clock advance cascade with predecessor-deadline chaining, timeouts, ON_TIME/AFTER_PASS/OUT_OF_ORDER selections, medical consent/share/supersede/deny/grant/expiry sweep, waiver SoD + info-request cap, rookie pool and UDFA waterfall, envelope/meta/pagination/auth shape. Confirmed on boot: all 13 stores empty, clock at the default, no disk persistence anywhere (`json.dumps` in `versioning.py` is an in-memory fingerprint only).

## Defects found and fixed this session
- `app.py` `PORT` default was `8080`; INSTRUCTION.md mandates `10000`.
- `logic.revoke_consent` lapsed OFFERED contracts only when clearance had been `CLEARED`; PRD §3.4 runs the five revocation steps unconditionally once every evaluation is `SEALED`.
- `forfeit_pick` was `sorted(set(...))`-ing `forfeited_round_numbers`; PRD §3.5 says the round number is *appended*, so duplicates and insertion order are now preserved.
- Earlier session: `versioning.commit()` moved out of `after_request` into `respond.py` handler exit points so responses show post-bump `version`.

## PRD ambiguities resolved (choice made)
1. Guards run in PRD §2.4 numeric order 1–40, first failure wins; rule 3 (body shape) precedes rule 4 (path existence), rule 7 (phase) precedes rule 8 (posture) — so `clock/advance` while `DRAFT_SUSPENDED` yields `ERR_CYCLE_PHASE_INVALID`, not `ERR_CYCLE_FROZEN`.
2. Per-action role narrowing enforced at the rule-2 position via a lenient `validate.peek("action")` -> `ERR_ROLE_NOT_PERMITTED`; an unknown/absent action falls through so rule 3 reports it.
3. Trade party checks: create/accept/GM-termination by a non-party -> `ERR_NOT_RESOURCE_OWNER`; counter by a non-party -> `ERR_SELF_TRADE_FORBIDDEN` (rule 15 wording).
4. FROZEN posture gates all cycle-scoped mutations **except** the phase endpoint, contract `VOID`, and `/_clock` — otherwise suspend/resume and post-close voids become impossible.
5. §3 specifics override generic rule 7: declaration `WITHDRAW` in `DECLARATION_OPEN|COMBINE_WEEK`; `FORFEIT` in `ORDER_FINAL|DRAFT_LIVE`; invitation `DECLINE`/`WITHDRAW`, terminations, eligibility determinations, evaluations, shares and claim `REJECT` ungated on phase.
6. Transition preconditions with no dedicated error id -> `ERR_INVALID_STATE_TRANSITION` 409 (lottery re-run, double finalize, `DECLARE_ELIGIBLE` season/declaration failure, early `CHECK_IN`, `MARK_NO_SHOW` before `ends_at`, non-future `consent_expires_at`, counter/accept alternation, `RESCIND` with non-PENDING picks, re-authorizing out-of-order, phase-ladder preconditions).
7. `DECLARE` against a non-`UNDECLARED` prospect -> `ERR_ALREADY_DECLARED` (rule 9 skipped for DECLARE so rule 28 is reachable), but the rule-16 deadline still fires first per numeric order.
8. Conditionally required body fields (`decision_note` on GRANT/DENY, `reason` on RESCIND, `scope`+`consent_expires_at` on GRANT, `denial_reason` on DENY/REVOKE, both conditional trade fields together) -> `ERR_INVALID_REQUEST` 400 at rule 3; the booking resource shape is the explicit exception -> `ERR_BOOKING_RESOURCE_MISMATCH` 422 at rule 21.
9. `MedicalStation`/`InterviewRoom` `OFFLINE` status and `station_code`/`room_code` uniqueness are not enforced — no error ids exist for either.
10. Medical clearance advances only from `PENDING` (PASS/PASS_WITH_NOTE->CLEARED, RED_FLAG->FAILED, FAIL_RECHECK unchanged).
11. Consent `REVOKE` sets clearance `UNVERIFIED` only when >=1 evaluation exists and all are `SEALED`; OFFERED contracts then lapse, `signing_status`->`UNSIGNED` unless a SIGNED contract exists.
12. `clock/advance` reports the **first** expired pick as `expired_pick_id` (the PRD names the field singular while the cascade can pass many) alongside `on_clock_pick_id`, `passed_count`, `lapsed_count`; `deadline_at` is nulled whenever a pick leaves `ON_CLOCK`.
13. Compensatory picks: `pick_in_round = club_count + awarded_sequence`, minted at the tail of `awarded_round`; `created_pick_count = rounds_count * club_count` with `compensatory_pick_count` reported separately; league-wide award ordering by (`claim_score` DESC, `created_at` ASC), per-club cap 4, league cap 8, net = departures - arrivals floored at 0; leftovers -> `REJECTED_CAP` with 0/0.
14. Selecting with a `PENDING` pick when no pick holds the clock -> `ERR_OUT_OF_ORDER_NOT_AUTHORIZED`.
15. The clock-set sweep marks shares `EXPIRED` and drops the active count but does **not** seal evaluations.
16. Rule 12 (`ERR_EVALUATION_SEALED`) is also applied at share GRANT — §2.4 lists it only for share create, but §3.4 names "still DISCLOSABLE" as a GRANT precondition and no other id fits.
17. No ownership enforcement on GETs (rule 6 says "mutations"); trade counter tier check only on the first counter out of `PROPOSED`; contract create is not gated on `signing_status` (an already-SIGNED prospect stays SIGNED, else `OFFER_OUT`).
18. Client-supplied numbers echo as supplied; computed Decimals serialize as `float`. Requests are serialized under a process-wide `RLock` despite `threaded=True`.

One genuine spec corner worth flagging: a non-playoff club with `lottery_combinations` 0 counts toward the lottery slot count (`min(4, pool size)`) but can never be drawn, so with >=3 pool clubs and a zero-combination club every sequence fails rule 26. The implementation follows the PRD text literally here.

## Step 7: Run tests and iterate — 2026-09-02T19:35:00.000Z

Verified green. Final sweep: all 8 rounds 148/148, zero failures, zero errors, no skips/xfails, no reaping signature in the log.

## Summary

**Iterations run:** 2 (first sweep: 142/148 in all 8 rounds, 6 deterministic failures, no flakiness; second sweep: 148/148 in all 8 rounds).

**Tests deleted:** none. All 6 failures traced to verbatim PRD sentences and survived STEP 1 coverage + unique-derivability.

**Fixes applied to `test_suite/`** (3 files, 4 tests — all STEP 2 test-vs-PRD faithfulness corrections; every assertion stayed an exact `error_id` / exact-value check):

- `test_03_bounded_review_and_negotiation_loops.py`, `TestTradeCounterLoop` (3 tests: `test_counter_loop_alternates_actors_and_climbs_to_the_round_cap`, `test_fourth_counter_is_refused_with_the_round_index_frozen_at_three`, `test_trade_at_the_round_cap_remains_acceptable_by_the_other_side`) — the counter payloads inverted the package orientation, sending the *acting* club's picks in `offered_pick_ids`. PRD §2.4 rule 23 is verbatim and explicitly lists `/counter` in its scope: "every pick in `offered_pick_ids` is owned by `proposing_club_id`, every pick in `requested_pick_ids` is owned by `receiving_club_id`" — no PRD sentence flips those roles on a counter, so the PRD-faithful server correctly answered `ERR_PICK_NOT_OWNED_BY_CLUB`. Counters now vary *which* proposing-club pick is offered (`r1p1` vs `r2p1`) while keeping the orientation; round-cap, alternation and the 0.0600 imbalance assertions are unchanged.
- `test_15_cycle_and_medical_error_paths.py`, `test_pass_on_the_on_clock_pick_is_refused_while_the_draft_is_suspended` — asserted `ERR_CYCLE_FROZEN` for a clock action on a `DRAFT_SUSPENDED` cycle. §2.4 states the precedence outcome verbatim: "Because cycle phase (rule 7) precedes cycle posture (rule 8), an operation attempted in the wrong phase reports `ERR_CYCLE_PHASE_INVALID` even when the cycle is also frozen", and rule 7 permits clock actions only in `DRAFT_LIVE`. The suite's own sibling `test_selection_during_a_suspended_draft_reports_the_phase_guard` (test_07) already asserts the phase guard for the identical state, so the suite was self-contradictory. Corrected to `ERR_CYCLE_PHASE_INVALID` (409).
- `test_18_version_freshness_and_reconciliation.py`, `test_draft_order_finalize_cannot_run_a_second_time` — asserted `ERR_INVALID_STATE_TRANSITION` on a replayed finalize. Rule 7 ("the lottery and the draft-order finalize only while it is `ORDER_PENDING`") fires before rule 9, and the first finalize already moved the cycle to `ORDER_FINAL`. Corrected to `ERR_CYCLE_PHASE_INVALID` (409).

**Fixes applied to `test_helpers/`:** none needed.

**Fixes applied to `implementation/`:**

- `workspace/implementation/logic.py`, `leave_clock()` — was nulling `deadline_at` whenever a pick left `ON_CLOCK` (an invention with no PRD basis). PRD §3.7 reads the expired pick's `deadline_at` *after* it has moved to `PASSED` ("with `on_clock_started_at` set to the *expired pick's* `deadline_at`"), so the stamp must survive the transition. Made it a no-op; `derive.on_clock_pick`/`current_overall_number` already key off `status` alone, so nothing else depended on the nulling.

One incidental note: the `order_final` fixture mints a 2-round cycle (4 picks), so `r3*` keys do not exist there — the counter-loop rewrite uses `r1p1` as the alternate proposing-club pick rather than a round-3 pick.

**Orchestrator independent verification (not the subagent's claim):** `ls` + `json.load` over `workspace/implementation/results.{1..8}.json` — all 8 files present, each `passed=148 total=148 failed=0 errors=0`; `sweep.log` tail shows `Results: 148/148 passed, 0 failed, 0 errors, 0 skipped`, duration 371.7s, and no `Terminated` reaping signature.

## Step 8: Finalize PRD — 2026-09-02T19:47:00.000Z

Done. Single edit; PRD_FINALIZED.md is a minimal patch.

## Line counts
- `PRD.md`: 521 lines / 108,706 bytes
- `PRD_FINALIZED.md`: 521 lines / 109,248 bytes
- Delta: 0 lines (+0.0%); +542 bytes (+0.50%) — one sentence group appended inside §3.7's existing deadline paragraph.

## Changes
- §3.7 (deadline paragraph, PRD line 356) — **insert** — pins that `on_clock_started_at` and `deadline_at`, once stamped, are never cleared: they survive a pick's departure from `ON_CLOCK` (so a `PASSED` / `USED` / `LAPSED` pick still reports the window it last held), are retained only as a record that gates nothing further, and stay null on a pick that never held the clock — `implementation/logic.py:174-182` (`leave_clock()` is now a no-op), consumed at `logic.py:205` (expiry cascade), `logic.py:250` (forfeit), `routes/picks.py:116` (ON_TIME selection), `routes/picks.py:158` (voluntary pass).

## Per-edit pre-edit search log

**Edit 1 — §3.7 clock-stamp retention**
(a) Subject: the lifetime of the two pick clock stamps `on_clock_started_at` / `deadline_at` — every write, clear, read and gate on them, anywhere in the implementation.
(b) Paths enumerated (grepped `deadline_at|on_clock_started_at` repo-wide, then read each site):
- `logic.py:165-171` `put_on_clock` — the only writer of both stamps (PENDING->ON_CLOCK); no path ever returns a pick to `PENDING`, so no re-stamp/overwrite case exists.
- `logic.py:174-182` `leave_clock` — now a pure no-op, called from all four departure sites.
- `logic.py:192-229` `clock_advance` — reads `current["deadline_at"]`, carries it as the successor's `on_clock_started_at`; also the PASSED->LAPSED conversion at DRAFT_COMPLETE, which leaves stamps untouched.
- `logic.py:247-258` `forfeit_pick` — reachable only from a `PENDING` pick (`routes/picks.py:176`), so a `FORFEITED` pick's stamps are always null; `logic.py:441-443` mints both as null (including picks minted directly `FORFEITED`).
- `routes/picks.py:81-85, 110-123` selections — deadline test applied only when source is `ON_CLOCK`; `AFTER_PASS` and `OUT_OF_ORDER` never read `deadline_at`, so a retained stamp gates nothing.
- `routes/picks.py:146-173` clock-action — status-is-`ON_CLOCK` check precedes the expiry check, so a retained stamp on an off-clock pick can never yield `ERR_CLOCK_ALREADY_EXPIRED`; TIMEOUT extends (not clears) `deadline_at`.
- `logic.py:598-654` `apply_phase` (incl. suspend/resume, DRAFT_COMPLETE->UDFA_WINDOW->CLOSED) — never touches pick stamps, matching the PRD's existing "keeps its existing `deadline_at` untouched" sentence at line 213.
- `derive.py:55-66` `on_clock_pick` / `current_overall_number` — key off `status` only, so retention cannot leak into cycle-level derived fields.
- `serialize.py:198-199` — both stamps are always serialized, so "still reports the window it last held" is literally observable.
(c) Wording adjustments made: (1) added "retained as a record that no longer gates any action against that pick", so the new sentence cannot be read as re-arming §2.4 rule 18 on `AFTER_PASS`/`OUT_OF_ORDER` selections or on off-clock clock-actions (verified against `routes/picks.py:81-85` and `146-154`); (2) scoped the claim to "once stamped" and added the explicit null case for picks that never held the clock, including ones minted directly into `FORFEITED`, so the mint defaults at `logic.py:441-443` and PRD line 304 stay true; (3) avoided any "never overwritten" phrasing so the TIMEOUT extension at `routes/picks.py:168` and the successor re-stamp in `put_on_clock` remain consistent.

## Items intentionally left unpatched (PRD already uniquely determines them)
- Counter package orientation (test_03 fix): §2.4 rule 23 is verbatim and explicitly lists `/counter`; `logic.check_pick_package` (logic.py:300-312) is called from counter with the trade's `proposing_club_id`/`receiving_club_id` as the owners, exactly as written. Pure test bug.
- Clock action on a `DRAFT_SUSPENDED` cycle (test_15 fix): §2.4 rule 7-before-8 note is verbatim; `routes/picks.py:143-144` orders `require_phase` before `require_unfrozen`. Pure test bug.
- Replayed draft-order finalize (test_18 fix): rule 7 ("the draft-order finalize only while it is `ORDER_PENDING`") is verbatim and `routes/cycles.py:97` checks phase before the `order_finalized_at`/lottery transition checks, which are shadowed after the first mint. Pure test bug; §3.5's "the mint runs exactly once" sentence remains true and was left verbatim.

## Step 9: Complete PRD — 2026-09-02T20:20:00.000Z

`PRD_COMPLETED.md` is complete. Final verification passes: §2.4 still numbers 1–40 with no gaps, the heading set is byte-identical to the source (no new sections), and the error-ID vocabulary is unchanged at 40 unique identifiers (nothing invented).

## Exit summary

**File sizes**
| | Lines | Bytes |
|---|---|---|
| `PRD_FINALIZED.md` (source) | 521 | 109,248 |
| `PRD_COMPLETED.md` | 526 | 126,556 |
| Delta | +5 | **+17,308** |

101 diff lines total; all changes are in-paragraph inserts/revisions plus one new paragraph (§2.4 rule-9 catch-all).

**Counts:** 52 changes — **32 ambiguity-pins**, **22 mismatch-revisions** (2 changes are both).

**Changes**

- §2.2 — revise — mismatch — `api_request_timestamp` comes from the real wall clock, never the logical clock — `response.py:16-27`
- §2.2 — insert — ambiguity — decimals render as JSON numbers, cents as integers, null-until-set as JSON `null` — `serialize.py:9-15`
- §2.2 — revise — ambiguity — `api_request_id` = `req_` + 20 chars from uppercase letters and digits — `response.py:8-14`
- §2.2 — insert — ambiguity — 404 `ERR_RESOURCE_NOT_FOUND` for unmatched path *and* wrong method; 400 for unparseable body; 500 `ERR_INVALID_REQUEST` for unhandled faults — `app.py:48-68`
- §2.3 — revise — ambiguity — pick lists order by `overall_number` then `created_at`; insertion order (`_seq`) is the universal final tiebreak — `db.py:86-88`, `logic.py:716-735`
- §2.4 (new para) — insert — ambiguity — rule 9 `ERR_INVALID_STATE_TRANSITION` is the catch-all for every §3 precondition stated without its own error identifier — `logic.py:62-63`
- §2.4 rule 2 — revise — ambiguity — per-action role narrowing enforced at the rule-2 position on four endpoints via `ERR_ROLE_NOT_PERMITTED`; `action` peeked leniently so malformed actions fall to rule 3 — `auth.py:34-49`
- §2.4 rule 3 — insert — ambiguity — JSON `null` = absent; empty-string query param = absent; absent/empty body = empty object — `validate.py:17-30,51-56,153-186`
- §2.4 rule 7 — revise — mismatch — replaced with an exhaustive per-action phase table plus the explicit list of mutations having no phase requirement — all 17 `require_phase` call sites
- §2.4 rule 8 — revise — mismatch — three exceptions to the `FROZEN` posture gate: the phase endpoint, the contract `VOID` branch, both facility-registration endpoints — `logic.py:596`, `routes/contracts.py:170`, `routes/facilities.py`
- §2.4 rule 15 — revise — mismatch — propose = differ test only; counter = party test; accept and termination instead use rule 6 `ERR_NOT_RESOURCE_OWNER` — `routes/trades.py:81,176,210,262`
- §2.4 rule 31 — revise — mismatch — clock-holder requirement is part of the guard; a `PENDING` selection with no pick on the clock yields `ERR_OUT_OF_ORDER_NOT_AUTHORIZED` — `routes/picks.py:97-108`
- §2.4 rule 36 — revise — mismatch — tier test covers both clubs on propose/accept, acting club only on counter, and only out of `PROPOSED` — `routes/trades.py:193-194`
- §2.5 — insert+revise — ambiguity — clock may move backwards with no monotonicity error; sweep records `EXPIRED` and the two derived figures follow — `routes/clock.py:16-22`, `logic.py:124-131`, `derive.py:130-138`
- §2.6 — revise — mismatch — audit fields read the logical clock; `updated_at` == `created_at` until first mutation; a no-op write is not a mutation; the two §2.8 parent bumps are forced — `versioning.py:20-62`, `db.py:71-80`, `respond.py:23-25`
- §2.7 — revise — mismatch — `prior_season_win_pct` / `strength_of_schedule` are range-checked only, stored and compared exactly as supplied — `routes/clubs.py:30-35`, `logic.py:323-331`
- §2.7 — revise — ambiguity — `snap_pct` range-checked but not quantized; raw value feeds both the band test and the advisory multiplication — `routes/claims.py:29`, `calc.comp_scores`
- §2.9 — revise — mismatch — cohesion list is exhaustive (five creation endpoints); a selection's `prospect_id` is existence-checked but never cohesion-checked — `routes/picks.py:68`
- §3.1 — insert — ambiguity — club registration has no phase requirement; `club_code` uniqueness includes `WITHDRAWN` clubs — `routes/clubs.py:57-65`
- §3.1 — revise — mismatch — `forfeited_round_numbers` appended in forfeit order, never re-sorted, may repeat a round — `logic.py:252-255`
- §3.1 — insert — mismatch — facility codes not enforced unique; `OFFLINE` station/room still accepts bookings — `routes/facilities.py:16-37`, `routes/bookings.py:86-89`
- §3.1 — revise — mismatch — `FROZEN` stops every cycle mutation, not just selections/trades/clock actions, subject to rule 8's three exceptions — `derive.py:14-20`
- §3.3 — revise — ambiguity — selector phase rule; `target_count` a required integer >=1 and <=320 — `routes/cycles.py:122-127`
- §3.3 — insert — ambiguity+mismatch — `duration_minutes` truncates seconds downward; no prospect-posture test on booking creation — `timeutil.py:49-50`, `routes/bookings.py:34-107`
- §3.4 — insert — ambiguity — sealing is one-way — `logic.py:114-116`, `routes/medical.py:256-257`
- §3.4 — insert — ambiguity — `denial_reason` persistence and its null paths — `serialize.py:177`, `routes/medical.py:248,255`
- §3.4 — insert — ambiguity — revocation cascade presupposes at least one evaluation — `logic.py:117`
- §3.5 — revise — ambiguity — a withdrawn club receives `draft_order_index` 0 and `pre_lottery_rank` 0 — `logic.py:406-408`
- §3.5 — revise — mismatch — finalize returns a summary; `created_pick_count` counts regular picks only; `first_overall_pick_id` reported even when `FORFEITED` — `logic.py:576-580`, `routes/cycles.py:103-104`
- §3.5 — insert — ambiguity — compensatory `pick_in_round` = `club_count` + `awarded_sequence`; always minted `PENDING` — `logic.py:420-450,516-523`
- §3.5 — insert — ambiguity — claim submission is not phase-bound; only `VERIFY` narrows to two phases — `routes/claims.py:41` vs `:104`
- §3.5 — insert — ambiguity — net entitlement computed for every club including `WITHDRAWN`, so a withdrawn club still wins its award — `logic.py:461-476`
- §3.5 — insert — ambiguity — `awarded_round` never clipped to `rounds_count`; `awarded_sequence` counted league-wide per round — `logic.py:495-500,550-565`
- §3.6 — revise — mismatch — on propose the differ test is `ERR_SELF_TRADE_FORBIDDEN`, but the acting-club test is rule 6 `ERR_NOT_RESOURCE_OWNER`, ahead of phase/posture — `routes/trades.py:77-82`
- §3.6 — insert — ambiguity — counter by a non-party yields `ERR_SELF_TRADE_FORBIDDEN`, after the alternation test — `routes/trades.py:174-177`
- §3.6 — insert — mismatch — accept by a non-party yields `ERR_NOT_RESOURCE_OWNER` before phase/posture; five remaining preconditions — `routes/trades.py:210-213`
- §3.6 — revise — ambiguity — acceptance sets `last_actor_club_id` to the accepting club — `routes/trades.py:246`
- §3.6 — insert — ambiguity+mismatch — termination role narrowing at rule 2; ClubGM must be a party (`ERR_NOT_RESOURCE_OWNER`), admin exempt; no phase requirement; `last_actor_club_id` untouched — `routes/trades.py:252-268`
- §3.6 — insert — mismatch — `conditional_round_number` / `conditional_condition_code` all-or-nothing, `ERR_INVALID_REQUEST` at rule 3 — `routes/trades.py:65-69`
- §3.6 — revise — ambiguity — conditional resolution requires `conditional_status` still `OPEN`; no phase requirement — `routes/trades.py:315-323`
- §3.7 — revise — mismatch — out-of-order guard includes the clock-holder requirement (inline restatement) — `routes/picks.py:97-108`
- §3.7 — revise — ambiguity — `AUTHORIZE_OUT_OF_ORDER` requires a `PENDING` pick; `FORFEIT` also admits `ORDER_FINAL` — `routes/picks.py:140-190`
- §3.7 — insert — ambiguity — a still-running clock makes the advance a no-op; the completion test runs on every advance — `logic.py:197-222`
- §3.7 — revise — ambiguity — four-field advance summary: `expired_pick_id` is the *first* pick passed (null if none), `on_clock_pick_id` null when the cascade exhausted `PENDING`, `passed_count` per call, `lapsed_count` only at completion — `logic.py:192-229`
- §3.7 — insert — ambiguity — the cycle needs at least one pick to reach `DRAFT_COMPLETE` — `logic.py:217`
- §3.8 — insert — ambiguity — a `UDFA` offer is confined to `UDFA_WINDOW`, a `DRAFTED` offer has no phase requirement; governing cycle is the prospect's — `routes/contracts.py:51-54`
- §3.8 — revise — mismatch — a new offer sets `signing_status` to `OFFER_OUT` only when not already `SIGNED`; the parent version bump is forced regardless — `routes/contracts.py:117-119`
- §3.8 — insert — ambiguity — signing has no phase requirement; governing cycle is the *club's*; `signing_status` becomes `SIGNED` from whatever it held — `routes/contracts.py:163-198`
- §3.8 — insert — mismatch — voiding has no cycle gate at all (neither phase nor posture) and sets `UNSIGNED` unconditionally — `routes/contracts.py:170-171,206-208`
- §3.8 — insert — ambiguity — the UDFA pool test runs before the new offer supersedes anything, so a club is charged for the offer about to lapse — `routes/contracts.py:83-98`, `derive.py:99-108`
- §4 — revise — mismatch — four endpoints return a bespoke summary object rather than a resource, all with `response_type` `object` — `routes/cycles.py:104,115,154`, `routes/clock.py:22`, `respond.py:18-20`
- §4 — insert — ambiguity — trailing slashes tolerated on every route — `app.py:25`

**Confirmed already-pinned (no edit):** §3.2 waiver review loop and SoD, §3.4 medical share/seal flow, the §5 error catalogue (all 40 IDs and statuses match `errors.py::ERROR_HTTP`), the §4 endpoint/role table (including that the real path is `/compensatory-claims/{id}/verify` and that no `GET /eligibility-waivers/{id}` exists), and §3.3's facility field defaults/ranges (15/0-60, 2/1-8).

**Deliberately left alone:** §3.5's "forfeits are honoured at mint time" paragraph is unreachable in practice (a `FORFEIT` requires `ORDER_FINAL`/`DRAFT_LIVE`, so `forfeited_round_numbers` is always empty at finalize) — unreachable, not mismatched, so no revision was warranted.

Scope respected throughout: only `PRD_COMPLETED.md` was written; `SCAFFOLD*.yaml` and `worklog.md` were never opened; no sibling task was accessed.

**Orchestrator notes on Step 9:**
- The subagent reported that `test_helpers/` and `test_suite/` "do not exist in this workspace" — it looked under `workspace/` rather than the task root, where both in fact live. This only cost it the *auxiliary* cross-reference; the alignment target (`implementation/`) was read exhaustively (136 tool uses), and the skill explicitly forbids treating tests as authority, so the scan's validity is unaffected.
- Verified `PRD_COMPLETED.md` ends at a real section boundary (final row of the §5 error table) with all 5 top-level sections present.
- Verified Steps 8 and 9 wrote only PRD docs: `implementation/logic.py` (19:26) and `test_suite/test_03_*.py` (19:27) both predate the Step 8 start (19:45), so the green 8/8 x 148/148 sweep result still describes the shipped artifacts.

## Pipeline complete — 2026-09-02T20:20:00.000Z

All nine steps done. Final state: 148 tests, 8/8 sweep rounds at 148/148, `PRD.md` / `PRD_FINALIZED.md` / `PRD_COMPLETED.md` all present.

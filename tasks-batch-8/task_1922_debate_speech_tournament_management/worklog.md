# Worklog — task_1922_debate_speech_tournament_management

## Step 2: Generate Scaffold — 2026-08-15T01:44:00.000Z

Done. All three scaffold artifacts were generated from the scenario description plus the skill specification alone (no sibling tasks were inspected), and the package passes `scaffold_lint.py` with `VERDICT: clean lint` (1555 test-recipe calls validated against the endpoint table, all FKs reverse-reachable).

**Files written (all three required):**
- `/home/ubuntu/github/CodingPRD/tasks/task_1922_debate_speech_tournament_management/SCAFFOLD.yaml` (1105 lines; §1.0–§1.7 only — no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1922_debate_speech_tournament_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1238 lines; single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1922_debate_speech_tournament_management/SCAFFOLD_CORNER_DESIGN.yaml` (1544 lines; single top-level key `scaffold_corner_design`)

**SCAFFOLD.yaml counts:** 13 entities, 9 state machines, 14 calculations, 17 ordered validation rows, 71 endpoints, 55 error codes, 4 roles, 3 OCC concurrency rules.

**Difficulty design: 20 instances** across all nine rules (dual_variant_calc 2, combinatorial_formula 3 — one per mode (a)/(b)/(c), non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2).

**Corner design: 69 instances** (59 active with full test recipes + 10 `excluded_because` stubs citing difficulty instances), spanning all nine claim-extraction-guide sections.

**Harder-than-expert calibration highlights:** the judge-obligation chain (per-division ceil × event-type rate × prelim-round count) feeds school confirm gating, tournament lock gating, hired-judge procurement sizing (purchase capped at live shortfall), and a depth-3 auto-release cascade on entry withdrawal; hired-judge fees are dual-variant (quote vs final diverge 35000 vs 30000 on identical data) with a tournament-wide premium tier ordered by created_at; the invoice discount tier is keyed on the pre-discount subtotal with pinned per-component rounding; the Swiss pairing algorithm pins backtracking order, bye selection, and created_at-only tie-breaks; rooms use half-open interval semantics while judges use a 30-minute buffered-gap semantics; OCC guards lock, pairing generation, and contract purchase. Two real replay bugs were caught and fixed during authoring (over-committed judge in the elimination round; hired-judge commitment bound scoping).

## Step 3: Copy Shared Files — 2026-08-15T01:45:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1922_debate_speech_tournament_management/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-15T01:56:00.000Z

All contracts pass. The PRD is complete and verified.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1922_debate_speech_tournament_management/workspace/PRD.md` — 389 lines.

**PRD section list**:
- §1. Introduction (2 paragraphs — business context + system scope/posture-gating angle)
- §2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control (all 4 roles with `identity:` translations — opaque for TournamentDirector/TabStaff, entity-backed for SchoolCoach/Judge; segregation of duties)
  - 2.2 API Response Structure (emitted verbatim from `section-2.2-response-structure.md`, confirmed byte-identical)
  - 2.3 Pagination (limit 10/1/100, offset 0, created_at ascending, meta fields)
  - 2.4 Common Resource Properties and Versioning (UUID id, 3-fractional-digit timestamps, version semantics; JudgeConflict/PairingEntry explicitly carry only `id` + `created_at`)
  - 2.5 The Logical Tournament Clock (2026-08-01T00:00:00Z startup default, `to_iso8601`/`current_utc`, all three window gates)
  - 2.6 Optimistic Concurrency Control on the Registration Graph (all 3 OCC rules with field name, error id, HTTP 412, stale-view framing)
  - 2.7 Validation Order and Priority (full pipeline order; conflict-before-turnover, caps-before-fiscal, low-point-before-field-validity orderings)
  - 2.8 Cross-Tournament Referential Integrity
  - 2.9 Monetary Precision, Rounding, and Pinned Arithmetic Order (integer cents, round half up, per-entry/per-component rounding prohibitions, pre-discount tier keying)
  - 2.10 Parallel Tournament Axes and Cascade Consistency (status × results_visibility independence, derived-field reconciliation)
- §3. Business Logic & Workflows (8 subsections, chronological): 3.1 Tournament Configuration/Divisions/Rooms; 3.2 Schools/Entries/Judges/Obligation Market (incl. withdraw 3-link cascade and lock); 3.3 Hired Judges/Contracts/Invoice (QUOTE vs FINAL tiered fee math, auto-release, discount tiers); 3.4 Rounds/Pairing Generation/Staffing (full algorithm: prelim debate adjacency then win-brackets, byes with 27 points, speech serpentine sections of 7, elim seeding, room half-open overlap, judge conflict/over-commit/30-minute turnover); 3.5 Ballots/Verification/Standings (submit window, low-point win, recall/verify/void cascade, raw vs high-low-adjusted points, opponent strength, standings tie-breaks); 3.6 Breaks/Elims/Placements (win threshold, bracket-size arithmetic, F-based placement tiers, completion); 3.7 Publishing/Certifying; 3.8 Catering/Awards logistics with freeze-at-submit
- §4. Endpoint Definitions (4-column table, all 71 endpoints, exact role lists)
- §5. Error Code Catalogue (2-column table, all 55 errors with exact HTTP statuses)

**Hard contract reports**:

```
Field coverage check:
- entities[].fields: 77 required, 77 present, 0 missing
- endpoints[].request_body: 38 required, 38 present, 0 missing
- endpoints[].query_params: 14 required, 14 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 17 checked, 17 expressed in prose (pipeline order §2.7; pairwise orderings for assign-judge, entry caps-vs-fiscal, low-point-vs-field-validity), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write capability + expected_tournament_version/expected_round_version/expected_school_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 43 checked, 43 fully expressed (from/to states, preconditions with error ids, all side-effect cascades incl. withdraw auto-release, ballot-void round reopen, complete champion/runner-up resolution), 0 missing
- calculations[]: 14 checked, 14 fully expressed in reconstruction-safe prose (no pseudocode/fuzzy words — verified mechanically), 0 missing
- validations[] conditions: 17 checked, 17 matchable to error_id in prose (all 55 error ids appear in §2/§3), 0 missing
- endpoints[].side_effects / applies_to: 71 checked, 71 expressed, 0 missing
- entities[].fields[] structured content: 111 checked, 111 reconstructible (defaults, ranges, initial nulls/zeros stated), 0 missing
- sibling-branch symmetry: 6 groups checked (re-confirm cycle, judge withdraw branches, debate/speech calc branches, QUOTE/FINAL, RAW/HIGH_LOW_ADJUSTED, CATERING/AWARDS), 6 with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 622
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verification: §4 table has exactly the scaffold's 71 method/path pairs (no missing, no extras); §5 has all 55 errors with matching statuses; zero fuzzy/approximating words or operator syntax in prose; document ends at §5 with no audit footer. The two forbidden index files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-08-15T02:14:00.000Z

Generation complete for task_1922. All counts below were verified by a programmatic audit (AST parse of every test function, tag resolution against both YAMLs, ≥8-word verbatim-grep of every docstring citation against PRD.md, pyflakes, pytest collection — 96 tests collect cleanly).

## Counts

**Queue A (Difficulty) — 20/20 instances emitted, 40 tests (exactly 2 per instance).** Every instance passed the PRD-first filter; all nine rules (dual-variant calc, combinatorial formula, cyclic/parallel state machines, both cascades, both priority pairs, all three boundary checks, both cross-entity gates, both temporal-overlap rules, both compensating invariants) have verbatim PRD coverage and uniquely-derived outcomes.

**Queue B (Corner) — 56/59 non-stub instances emitted (1 test each); 3 skipped** (gaps left as gaps, no placeholders/markers):
- `entities/tournament_creation_defaults` — asserts `version == 1`; PRD §2.4 pins only "increments by one on every mutation", never the initial value → not uniquely derivable.
- `entities/entry_computed_field_input_ignored` — asserts `version == 1` (same gap), and PRD never states whether client-supplied computed fields are ignored vs rejected.
- `validations/start_elims_with_untabulated_round_rejected` — with a PAIRED prelim round and no bracket set, both `ERR_ROUNDS_NOT_TABULATED` and `ERR_BREAKS_NOT_DETERMINED` fail simultaneously; PRD §2.7 pins no order within the aggregate-gate step → the asserted single error_id is not uniquely derivable.

**10 `excluded_because:` stubs** (2 state_machines, 3 calculations, 4 errors, 1 cross_cutting) were not translated; all cross-references resolve to real queue-A instances.

## Files written

`test_helpers/` (9 files): `types.py` (TypedDicts/enums; JudgeConflict & PairingEntry correctly omit `updated_at`/`version`), `api_client.py` (all 60 endpoints + clock), `api_errors.py` (full 60-id catalog + HTTP map registered via `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (entity-backed `make_coach_headers`/`make_judge_headers` builders; opaque shared constants for director/TabStaff), `fixtures.py` (tiered composite builders: generic registration-scenario builder, round-flow drivers with dynamic pairing-membership capture, and bespoke heavy fixtures for the 3-round bye divergence, 2-round 6-entry break/publication flows, room/judge contention, and contract scenarios), `__init__.py` (barrel).

`test_suite/` (conftest.py + 10 files, 96 tests): test_01 auth/RBAC/404 (18), test_02 phases/windows (6), test_03 structure/caps (13), test_04 obligation/lock/OCC (7), test_05 fees/invoice/credit (10), test_06 contracts (6), test_07 pairing/staffing (11), test_08 ballots (13), test_09 void-cascade/logistics (6), test_10 breaks/standings/publication (6).

## Tag confirmation

Every emitted test's docstring ends with exactly one `Design: Difficulty/<rule_id>/<instance>` or `Design: Corner/<section>/<instance>` line copied verbatim from the source YAML `name:` — verified programmatically (1 tag per test, all tags resolve, no stub tags, no untagged tests, no skip/xfail markers). Every docstring citation contains a contiguous ≥8-word span that greps literally in PRD.md.

One design note: for `catering_order_submit_freezes_counts` I reordered the recipe's setup (create the DRAFT order before committing the judges) so the asserted headcount 12 / meal 14 is reached via a registration-graph mutation — under a strict "born at 0, recompute on mutation" reading the original ordering would leave the freshly created order at 0; the reorder makes every asserted value derivable under any faithful PRD reading while preserving all asserted numbers (12/14 before submit, 15 live vs 14 frozen after).

## Step 6: Generate Implementation — 2026-08-15T02:14:00.000Z

Implementation complete and verified. Summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1922_debate_speech_tournament_management/workspace/implementation/`)

- **start.sh** — executable launcher; guards the pip install behind `python3 -c "import flask"` (no-op on per-test reboots), then `exec python3 app.py` in the foreground; binds `0.0.0.0:$PORT` (default 10000)
- **requirements.txt** — flask>=3.0,<4.0
- **core.py** — in-memory `Store` (dicts keyed by id, starts empty, zero seeding), logical clock (default exactly `2026-08-01T00:00:00Z`, never wall-clock), monotonic 3-fractional-digit timestamps, `ApiError`, exact response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields `limit/offset/total_count/has_more` in meta), auth (`X-User-ID`/`X-User-Role`, 4 roles), pagination parsing
- **services.py** — all calculation rules: judge obligation (ceil per division × prelim_round_count), coverage/shortfall, tiered hired-judge fee (QUOTE vs FINAL variants, premium threshold 8, chronological ordering by created_at then rounds_requested), per-entry late surcharge (round-half-up at confirm), school invoice (pre-discount tier selection, per-component rounding, payments), speaker-point/rank-point tabulation with high-low adjustment, opponent strength (wins-first pinned order), standings tie-breaks (created_at ASC final), break determination, elim placement tiers, qualification points, logistics demand (integer ceil of ×1.10), pairing engine (adjacent/bracketed debate with exhaustive created_at-guided backtracking under same-school + rematch hard constraints, capacity-aware serpentine speech sections, seeded elim pairings, bye selection/award), auto-release cascade, serializers
- **app.py** — Flask entrypoint, blueprint registration, envelope-shaped error handlers
- **routes_a.py** — tournament lifecycle (both axes), clock endpoint, schools, divisions, determine-breaks, standings
- **routes_b.py** — entries (caps, credit projection, confirm/withdraw cascades), judges, judge-conflicts, rooms
- **routes_c.py** — rounds, generate-pairings (phase gate → OCC → state → prior-round gates), open-ballots, tabulate, pairings staffing (conflict-of-interest → over-committed → turnover ordering; half-open room overlap; 30-minute judge buffer with exactly-30 allowed)
- **routes_d.py** — ballots (low-point-win outranks field validity, at create and re-checked at submit; submit window ends_at+60min; void cascade reopening TABULATED rounds), hired-judge contracts (full lifecycle), logistics orders (live recompute, freeze at submit, AWARDS breaks gate)

## Endpoint count
**71/71** routes implemented — matches the scaffold endpoint table exactly, including `POST /_clock/set_current_utc`.

## Boot verification
`bash start.sh` with `PORT` set boots cleanly in under a second; store is empty on fresh boot (verified `total_count: 0`), unknown routes return envelope-shaped 404s. Two smoke suites (324 assertions total) passed against fresh processes: full debate tournament end-to-end (registration → obligation market → lock with OCC → prelims with same-school pairing repair → ballots/verify/void cascade → breaks → elims → champion → publish → certify), full speech flow (serpentine sections, rank points, top-2 final section, rank-ordered champion/runner-up), bye award (VERIFIED pairing, +27 points, emitted last), withdraw auto-release draining a REQUESTED contract to auto-CANCELLED, late-fee surcharge (1150 = round-half-up of 1000×1.15), credit-limit 402, tiered fees, invoice/payments, turnover/double-booking/window boundaries, and RBAC/ownership/404/412 error paths.

## Step 7: Run Tests and Iterate — 2026-08-15T02:31:00.000Z

## Summary — clean 8-round sweep achieved (96/96 × 8)

**Iterations run:** 3 sweeps (24 parallel round-runs of 96 tests each).

**Sweep 1:** 93/96 × 8 — three tests failed deterministically in every round.
**Sweep 2:** the three fixes held, but 2 tests flaked intermittently with `ConnectionError: Connection reset by peer` (Werkzeug dev server under 8-way parallel per-test restart load).
**Sweep 3:** 96/96 × 8, zero failures, zero errors.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1922_debate_speech_tournament_management/test_suite/test_08_ballots_and_verification.py` — `test_thirty_one_and_nineteen_rejected`: the low-case payload `{winner: 19, loser: 25}` violated both the range rule and the low-point-win rule; PRD §2.7 pins LPW above field-validity checks, so the uniquely-derived outcome was `ERR_LOW_POINT_WIN_NOT_FLAGGED`, not the asserted `ERR_SPEAKER_POINTS_OUT_OF_RANGE`. Moved the out-of-range 19 onto the loser (`{winner: 25, loser: 19}`) so only the range rule fires — preserves the boundary intent.
- `/home/ubuntu/github/CodingPRD/tasks/task_1922_debate_speech_tournament_management/test_suite/test_10_breaks_standings_and_publication.py` — `test_opponent_strength_breaks_the_tie`: asserted `b2["opponent_strength"] == 3`, but the test's own comment arithmetic ("C2 0 + A1 2") yields 2, and I proved exhaustively that no arrangement reachable under PRD §3.4's pinned pairing algorithm can produce 3 while satisfying the test's other constraints (C1 exactly 1 win, os 2). Verified the PRD-derived value 2 by hand-trace and by a live end-to-end run; corrected the constant and comment.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1922_debate_speech_tournament_management/workspace/implementation/services.py` — `auto_release_contracts`: the surplus basis used `covered_judge_rounds − obligation`, which by PRD §3.2's own coverage definition excludes `REQUESTED` contracts — rendering the PRD-mandated drain-and-auto-cancel of `REQUESTED` contracts inert exactly when a school requested precisely its shortfall and then withdrew entries. Now includes still-`REQUESTED` contracts' active rounds in the surplus basis, giving the §3.2 withdrawal cascade its intended effect. Live-verified: 4-entry/4-round-judge/4-round-request scenario drains to `rounds_released=4`, `CANCELLED`, invoice 5000.
- `/home/ubuntu/github/CodingPRD/tasks/task_1922_debate_speech_tournament_management/workspace/implementation/app.py` + `start.sh` + `requirements.txt` — serve via `waitress` (threads=8, channel_timeout=30) with Flask-dev-server fallback, matching the pattern proven in sibling tasks; eliminated the intermittent connection resets seen in sweep 2. No PRD behavior changed.

All findings trace to verbatim PRD sentences; no test was weakened, skipped, or deleted, and no PRD-required implementation check was removed.

## Step 8: Finalize PRD — 2026-08-15T02:36:00.000Z

Done. `PRD_FINALIZED.md` is written with exactly one inline revision.

## Line counts and delta

- `PRD.md`: 388 lines — `PRD_FINALIZED.md`: 388 lines — 0% line-count delta (single intra-line revision at line 156, ~+110 chars).

## Changes (one bullet per change)

- **§3.2 (withdrawal cascade, link 2)** — revise — pinned the surplus basis: "the surplus is measured as the amount by which the school's `covered_judge_rounds` plus the active rounds of its still-`REQUESTED` contracts exceeds its `judge_obligation_rounds` (never below zero, so a school still in shortfall drains nothing)". The original wording said only "surplus hired coverage", which — read against §3.2's own `covered_judge_rounds` definition (excludes `REQUESTED`) — made the PRD-mandated drain-and-auto-cancel of `REQUESTED` contracts inert exactly when a school requested precisely its shortfall then withdrew entries — `implementation/services.py:772-775` (`auto_release_contracts` surplus formula), guarded by `services.py:775-776`.

## Step 7 items requiring no PRD edit

- **`test_08` LPW ordering** — pure fixture bug. PRD §2.7 (line 106) and §3.5 (line 208) already pin `ERR_LOW_POINT_WIN_NOT_FLAGGED` above field-validity checks; impl `routes_d.py:42-56` checks LPW first (when computable), matching PRD verbatim. Kept prose unchanged.
- **`test_10` opponent_strength constant** — pure fixture arithmetic bug (asserted 3, PRD-derived value 2). PRD §3.5 (line 220) pins the computation exactly ("all wins recomputed first, then sum of current wins of distinct preliminary opponents"); impl `services.py:364-377` matches. Kept prose unchanged.
- **waitress serving (`app.py`/`start.sh`/`requirements.txt`)** — infrastructure hardening, explicitly no behavior change; PRD contains no server-implementation content. Nothing to pin.

## Per-edit pre-edit search log

**Edit 1 (§3.2 surplus basis):**
- (a) Subject: definition of the "surplus" drained from `REQUESTED`/`CONFIRMED` contracts by the withdrawal cascade.
- (b) Impl paths enumerated and read/grepped: `services.py:758-801` (`auto_release_contracts` — surplus formula, newest-first drain loop, `rounds_released` cap, `CONFIRMED`-only final-fee recompute via `hired_fee` FINAL variant, `REQUESTED`-fully-drained → `CANCELLED`); `services.py:166-206` (`school_derived` — `covered_judge_rounds`/`shortfall_rounds` definitions excluding `REQUESTED`); `routes_b.py:164-192` (`withdraw_entry`, the sole cascade caller — confirmed by repo-wide grep for `auto_release`); `routes_d.py:285-300` (contract create sizing against `shortfall_rounds`, `rounds_released` born 0); `routes_a.py:346` (school-confirm gate via `shortfall_rounds`); `services.py:214-235` (`hired_fee` QUOTE vs FINAL candidate sets); `services.py:987-1001` (`serialize_contract`, `rounds_active`); repo-wide grep for `rounds_released` confirmed no other mutation site.
- (c) Wording adjustment: phrased the measure as "`covered_judge_rounds` plus the active rounds of its still-`REQUESTED` contracts" so §3.2's existing `covered_judge_rounds` definition — reused untouched by school-confirm, contract-create sizing, and serializers — is referenced, not redefined; added the "(never below zero…)" floor mirroring the `surplus <= 0 → return []` guard; drain ordering, cap, fee-recompute, and auto-cancel clauses kept verbatim so every enumerated path remains correctly described.

## Step 9: Complete PRD — 2026-08-15T02:48:00.000Z

All edits verified. The diff touches 26 hunks (25 in-place revisions + 1 added table row), line count 388 → 389, char count 62,814 → 66,898 (+4,084).

## Summary

**Source:** `workspace/PRD_FINALIZED.md` (388 lines, 62,814 chars) → **PRD_COMPLETED.md** (389 lines, 66,898 chars; **+1 line, +4,084 chars**, all in-place paragraph inserts/revisions plus one catalogue row; no new sections).

**Counts:** 24 ambiguity-pins, 4 mismatch-revisions (28 changes total).

### Changes

- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped (not rejected), unparseable values fall back to defaults, `has_more` = (offset + returned) < total_count, filters match by equality without 404s — `implementation/core.py:183-209`
- §2.4 — insert — ambiguity — a resource is born with `version` 1 — `implementation/routes_a.py:106` (and every other create block)
- §2.5 — revise — ambiguity — clock endpoint *sets* the clock to any supplied instant (no forward-only constraint; "advances" was loose) — `implementation/routes_a.py:38-51`
- §2.5 — insert — ambiguity — window-check positions: open→after phase gate; lock→after phase/concurrency/lock-ready gates; ballot submit→after state and content checks — `implementation/routes_a.py:131-136,147-162`, `implementation/routes_d.py:175-192`
- §2.6 — insert — ambiguity — absent or non-integer expectation field fails comparison → `ERR_STALE_VERSION` — `implementation/routes_a.py:151-154`, `routes_c.py:126-129`, `routes_d.py:283-286`
- §2.7 — insert — ambiguity — ownership-vs-existence ordering: direct school-id ownership precedes existence; chained ownership (entry/judge/ballot path resources) surfaces the resource's 404 first — `implementation/routes_a.py:334-337`, `routes_b.py:135-139`, `routes_d.py:159-167`
- §2.7 — insert — ambiguity — enumerates exactly which writes are gated on `REGISTRATION_OPEN` (entry create/confirm/withdraw, judge commit/withdraw, school confirm/unconfirm); school/judge/conflict/contract/order creation and contract lifecycle actions are not phase-gated — `implementation/routes_d.py:273-311,340-446` (no phase checks)
- §2.7 — revise — mismatch — LPW check outranks field-validity *whenever computable*, not unconditionally — `implementation/routes_d.py:42-56`
- §2.7 — insert — ambiguity — unpinned field-level failures (malformed JSON, missing/mistyped/out-of-range fields) → `ERR_VALIDATION` (HTTP 400) at point of consumption — `implementation/core.py:163-175`
- §2.8 — insert — ambiguity — cross-tournament integrity check runs after business-rule checks (caps, double-booking, COI, ceiling, turnover) — `implementation/routes_b.py:53-70`, `routes_c.py:234-247,289-308`
- §3.1 — insert — ambiguity — no ordering constraint enforced between the two registration instants; `late_fee_surcharge_pct` accepts any numeric value — `implementation/routes_a.py:67-90`
- §3.2 — insert — ambiguity — `credit_limit_cents` accepts any integer, no sign constraint — `implementation/routes_a.py:290-292`
- §3.2 — insert — ambiguity — `confirmed_entry_count` counts entries in the invoice status set (`CONFIRMED`/`COMPETING`/`ADVANCED`/`ELIMINATED`/`FINISHED`) — `implementation/services.py:166-171`
- §3.3 — revise — ambiguity — `fee_quote_cents` computed once at creation, never recomputed; auto-release recomputes the final fee only for `CONFIRMED` contracts — `implementation/routes_d.py:308`, `services.py:793-796`
- §3.4 — insert — ambiguity — `starts_at` not strictly before `ends_at` → `ERR_ROUND_INVALID_STATE` (409) — `implementation/routes_c.py:66-67`
- §3.4 — revise — ambiguity — `pairings_total` counts all created pairings including the bye; `pairings_verified_count` counts the born-`VERIFIED` bye from creation — `implementation/routes_c.py:139-140`
- §3.4 — insert — ambiguity — bye's win + 27 points reflected in entry stats immediately at generation; bye's single member recorded as `AFF`, `draw_position` 1 — `implementation/services.py:556-565`
- §3.4 — revise — ambiguity — membership listings use default `created_at` order, which coincides with `draw_position` within a pairing — `implementation/routes_c.py:349`, `services.py:503-513`
- §3.4 — insert — ambiguity — assign-room requires `PENDING_STAFFING`/`STAFFED` (else `ERR_PAIRING_INVALID_STATE`); a pairing's booking/turnover slot is its round's `starts_at`/`ends_at` — `implementation/routes_c.py:36-38,231-233`
- §3.4 — revise — ambiguity — assign-judge requires the pairing to have no judge currently assigned — `implementation/routes_c.py:268-270`
- §3.4 — revise — mismatch — replaced "room reassignment removes the room" reversion clause (impl never removes a room): reassigning a room on a `STAFFED` pairing replaces `room_id` and leaves it `STAFFED` — `implementation/routes_c.py:248-251`
- §3.4 — revise — ambiguity — open-ballots from a non-`PAIRED` round → `ERR_ROUND_INVALID_STATE` — `implementation/routes_c.py:151-153`
- §3.5 — insert — ambiguity — ballot creation not gated on pairing state or on absence of other ballots; only submission requires `BALLOT_RELEASED` — `implementation/routes_d.py:104-132`
- §3.5 — revise — mismatch — LPW computability detail (winner is a member and all speaker points present integers; otherwise field errors surface first) — companion anchor to the §2.7 revision — `implementation/routes_d.py:40-56`
- §3.5 — revise — ambiguity — tabulate from a non-`BALLOTS_OPEN` round → `ERR_ROUND_INVALID_STATE` — `implementation/routes_c.py:172-174`
- §3.7 — insert — ambiguity — an entry with no `final_placement` earns the `NON_BREAKING` value of 1 qualification point — `implementation/services.py:752`
- §3.8 — revise — mismatch — order live demand fields are not born at 0; they are recomputed live on every read from creation (a fresh catering order's `headcount_demand` already includes the staff count) — `implementation/routes_d.py:470-482`, `services.py:1004-1045`
- §5 — insert — ambiguity — added `ERR_VALIDATION` | 400 Bad Request catalogue row — `implementation/core.py:166-175`

The two most substantive corrections were true mismatches: PRD claimed logistics orders are born with demand counts at 0 (impl computes them live on every read, confirmed by test_09 asserting `headcount_demand == 12` at creation), and PRD implied a room could be removed via reassignment triggering a staffing reversion (impl has no such path). Everything else pinned observable behaviors — validation orderings, check positions, count semantics, and the previously uncatalogued `ERR_VALIDATION` — that the prose had left open.

# Worklog — task_1132_robotics_competition_team_event_management

## Step 1: Create task directory — 2026-08-10T22:05:00.000Z

Pre-assigned output folder `tasks/task_1132_robotics_competition_team_event_management` with `workspace/` subdirectory already existed (per pipeline dispatch); Step 1 auto-index scan skipped as instructed. Directory verified present and empty.

## Step 2: Generate scaffold — 2026-08-10T22:49:00.000Z

All three files exist, parse cleanly, and pass `scaffold_lint.py` with `VERDICT: clean lint`.

## Final Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1132_robotics_competition_team_event_management/`):
- `SCAFFOLD.yaml` (113 KB) — §1.0–§1.7, no forbidden top-level keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (66 KB) — single top-level `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (30 KB) — single top-level `scaffold_corner_design`

**Counts**:
- Entities: **17** (expert max 15) — FrcEvent, Team, Person, ScreeningRecord, BuildSeasonMilestone, PartOrder, RobotInspection, ComplianceViolation, Match, Alliance, AllianceSelectionRound, MatchScoreBreakdown, QueueSlot, FieldResetLog, Award, InterviewSlot, TravelBooking
- State machines: **14** (expert min 4)
- Calculations: **11** (incl. dual-variant on score_match, team_ranking_score, travel_reimbursement)
- Endpoints: **134** (expert max 32) — includes 1 test-driving `/_clock/set_current_utc` (default 2026-05-01T00:00:00Z)
- Errors: **59** (expert max 30)
- Roles: **14** (incl. segregation_of_duties across ScreeningOfficer/Inspector/LeadInspector/Scorekeeper/HeadReferee/ProcurementOfficer/TravelOfficer/JudgeAdvisor)
- Validations: 22 (priority-ordered across auth/existence/state/safety/temporal/referential/fiscal/constraint)
- Concurrency rules (OCC): 3 (Person screening approve, AllianceSelectionRound pick, FrcEvent start-matches)

**§1.8 difficulty design**: 9 rules × **3 instances each = 27 total** (expert min is 2 per rule)
- `dual_variant_calc`: score_match (Match), team_ranking_score (Team), travel_reimbursement (TravelBooking)
- `combinatorial_formula`: tiered mode (a), nested rounding order mode (b), circular-dependency waterfall mode (c)
- `non_linear_state_machine`: Match cyclic replay, Person cyclic screening expiry, PartOrder branching
- `transitive_cascade`: team_withdraw (depth 3), mentor_expiry→posture (depth 3), critical_violation→FROZEN (depth 2)
- `priority_pair_validation_conflict`: state vs business_fiscal, business_safety vs business_temporal, existence vs state
- `boundary_precision_check`: ranking_points strict `>` threshold, capacity boundary, FIELD_RESET_MIN_SECONDS 300 vs 299
- `cross_entity_state_dependency`: Team→FrcEvent posture, Match→FieldResetLog, TravelBooking→Team
- `resource_temporal_overlap`: judge interview half-open, field aggregate capacity, UNBAG_WINDOW closed interval
- `compensating_invariant`: registered_team_count, ranking_points reversal on replay, PartOrder budget

**§1.9 corner design**: 9 sections, **29 instances** covering entities (creation, required-field, computed, type constraint, not-found), state machines (invalid transitions, terminal lockdown, side effects, preconditions), calculations (correctness, floor, filtering, seeding), validations (RBAC, temporal, OCC, segregation), endpoints (pagination, computed read, clock default), errors (triggerability), RBAC (exclusive ops), cross-cutting (OCC, scheduled actions), and consistency (immediate visibility).

**Harder-than-expert difficulty measures applied**:
1. Volume beyond expert ceilings: 17 entities, 134 endpoints, 59 errors, 14 state machines, 14 roles, 22 validations (vs expert maxes ~15/32/30/4+)
2. Density per §0.4: 8 cross-cutting complexity layers layered simultaneously (OCC + cascading side-effects + dual-variant calc + rate thresholds + derived-field reconciliation + ops-run checkpoint + selector policy + temporal windowing)
3. Instance count above the rule minimum: 3 instances per rule (27 total) instead of the 2 minimum
4. Selector policies (`seed_alliance_captains`, `alliance_pick_order`, `award_winner_selection`, `championship_qualification_run`) all pin eligibility filter + ranking + tie-break (`ranking_score DESC, ranking_tie_break DESC, team_number ASC, created_at ASC`) + empty-pool fallback — never `id`
5. Segregation-of-duties enforced at 5 distinct pivot points (screening self-approve, inspector own-team, score/finalize same user, part-order submitter/approver, violation opener/resolver)
6. Three distinct OCC concurrency rules (Person, AllianceSelectionRound, FrcEvent)
7. Posture-driven gating: derived `posture ∈ {OPEN, RESTRICTED, FROZEN}` blocks writes across multiple endpoints
8. Boundary precision pinned: `>` (not `>=`) on ranking bonus thresholds, inclusive capacity at `== team_capacity`, inclusive FIELD_RESET_MIN_SECONDS at 300, tier boundary at exactly 200000 cents, closed-interval UNBAG_WINDOW vs half-open interview slots

**Lint verdict (verbatim)**:
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

(Orchestrator note: Step 2 subagent required two resumptions — first turn ended before writing files (empty disk; resumed via SendMessage), second turn stopped after self-identifying an endpoint lint gap (resumed to add flat filtered-list GET endpoints and re-lint). Final state verified by orchestrator: all three YAMLs on disk, 113KB/67KB/31KB, yaml.safe_load clean.)

## Step 3: Copy shared files — 2026-08-10T22:57:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1132_robotics_competition_team_event_management/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-10T23:05:00.000Z

PRD.md generated at `/home/ubuntu/github/CodingPRD/tasks/task_1132_robotics_competition_team_event_management/workspace/PRD.md` — 510 lines, 78,885 bytes.

## Coverage Audit Summary

**Contract 1 — Field-Name Coverage:**
- entities[].fields + common fields + endpoints[].input + path params: 119 required, 119 present, 0 missing
- Status: PASS

**Contract 2 — Rule Coverage:**
- validations[] with priority: 22 priority levels expressed in §2.7 in fixed order, each with error_id and HTTP status
- concurrency_rules[] OCC rejections: 3 rules — `expected_person_version` on screening approve, `expected_round_version` on alliance pick, `expected_event_version` on start-matches — all named in §2.4 and §3 with `ERR_STALE_VERSION` / HTTP 412
- state_machines[].transitions: all 14 state machines' transitions expressed in §3 with preconditions and side_effects (FrcEvent, Team, Person, PartOrder, RobotInspection, ComplianceViolation, Match, QueueSlot, FieldResetLog, Alliance, AllianceSelectionRound, Award, InterviewSlot, TravelBooking)
- calculations[]: all 11 covered with formulas in prose — `score_match` (provisional vs final variants with 5/10/30 penalties), `ranking_points` (2/1/0 with strict > thresholds 25/20 and +1 bonuses), `team_ranking_score` (chronological vs forward_looking variants, 4dp ROUND_HALF_UP), `generate_match_schedule` (MIN_TEAMS 6, ROUNDS 8, FIELD_RESET 300s), `seed_alliance_captains` (ALLIANCE_COUNT 8, MIN_MATCHES 1), `alliance_pick_order` (snake draft), `award_winner_selection` (per-kind branches), `event_posture` (CRITICAL_FREEZE_THRESHOLD 3), `travel_reimbursement` (marginal variant pinned, tier1 200000@0.80, tier2@0.50, per-tier rounding, mode caps 1500000/800000/400000/300000), `championship_qualification_run` (4 buckets), `screening_expiry`
- validations[] conditions: every error_id matchable to its trigger condition in §2/§3 prose
- endpoints[].side_effects: consolidated cascade reference in §3.9 plus per-workflow narrative
- entities[].fields[] structured content: types, defaults, nullability, enum values, and constraints all placed on the owning entity
- sibling-branch symmetry: parallel branches (e.g. 4 award_winner_selection branches, 2 team_ranking_score variants, 2 travel_reimbursement variants) rendered with equal density
- Status: PASS

**Contract 3 — §3 Path Purity:**
- backtick tokens scanned in §3: 769
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- Status: PASS

**Other checklist items:**
- §2.2 emitted verbatim (byte-identical to canonical block, only trailing newline differs)
- §2.3 states limit=10/[1,100], offset=0, sort=created_at ascending, all four pagination meta fields
- All 14 roles spelled exactly; identity (entity_backed vs opaque) translated per role
- All 56 state enum values appear as UPPERCASE strings (including the 7 states that appear only inside transition-pair tokens, matching the example PRD's style)
- All 59 error_ids from the catalog appear backticked in §2/§3; §5 table has only 2 columns
- §4 endpoint table has 134 rows (matches scaffold count) with only 4 columns
- Physical constants embedded: 56.7 kg, 304 cm, 300 s, 8 rounds, 6 min teams, 8 alliances, 1 min match for seeding, 180d/90d screening windows, $2000 tier-1 limit, 80%/50% rates, mode caps
- §3 contains no field lists, no schema tables, no declared foreign keys (FK references are expressed via workflow narrative and the foreign-key paragraph in §2.10)

## Step 5: Generate unit tests — 2026-08-10T23:42:00.000Z

Generation complete. Summary:

## Tests emitted — 67 total

**Queue A (Difficulty): 20 of 27 instances → 40 tests** (each emitted instance has ≥2 tests, tagged `Design: Difficulty/<rule_id>/<name>`)
- dual_variant_calc: score_match provisional/final (2), team_ranking_score chronological vs forward-looking (2), travel marginal vs average (2)
- combinatorial_formula: travel tier/cap modes (2), championship waterfall bucket ordering (2)
- non_linear_state_machine: match replay cycle (2), part-order branching/terminal lockdown (2)
- transitive_cascade: withdraw cascade (2), mentor-expiry→posture (2), critical-violation→FROZEN (2)
- priority_pair_validation_conflict: existence-vs-state on confirm (2, incl. the verbatim PRD "frozen event" example)
- boundary_precision_check: RP auto/endgame strict-> (2), capacity boundary (2), 300s field-interval boundary (2)
- cross_entity_state_dependency: confirm-vs-posture (2), take-field-vs-reset-log (2), travel-vs-qualification (2)
- resource_temporal_overlap: judge half-open overlap (2)
- compensating_invariant: registered_team_count confirm/withdraw (2), ranking reversal on replay (2)

**Queue B (Corner): 27 of 29 non-stub instances → 27 tests** (tagged `Design: Corner/<section>/<name>`); all sections covered.

## Instances skipped (PRD-first filter failures — gaps left as gaps)

Queue A (7):
- `travel_reimbursement_mode_b_nested_rounding_order` — asserted value 160001 hinges on round(0.5)=1; PRD specifies half-up only for ranking aggregates, not reimbursement → not uniquely derivable.
- `person_screening_cyclic_via_expiry` — claimed EXPIRED→IN_REVIEW re-entry contradicts the state machine (EXPIRED terminal) and PRD is silent; reject-vs-reopen ambiguous.
- `state_vs_business_fiscal_on_part_order_approve` — PRD states no event-status gate for approve; the "budget cap" has no numeric value anywhere in PRD.
- `business_safety_vs_business_temporal_on_inspection` — the paired temporal rule (field reset) does not apply to the inspection endpoint; pair not constructible.
- `field_match_interval_aggregate_capacity` — "one ON_FIELD match per field" rule absent from PRD; residue owned by the take-field instance.
- `unbag_window_overlapping_milestones` — no UNBAG_WINDOW overlap rule in PRD at all.
- `budget_invariant_on_part_order_cancel` — no `budget_remaining` field or budget-cap value in PRD.

Queue B (2):
- `frc_event_create_missing_required_field_returns_invalid_request` — missing-field → ERR_INVALID_REQUEST trigger appears only in the error table, never in PRD prose.
- `closed_event_cannot_transition` — recipe asserts ERR_INVALID_STATE where PRD pins ERR_MILESTONE_MISSING; terminal-lockdown salvage is priority-4-vs-6 ambiguous for event-self transitions.

## Helpers written (test_helpers/, 9 files)
`types.py` (26 enums), `api_client.py` (ApiClient subclass, ~90 endpoint methods incl. flat routes + `/_clock/set_current_utc`), `api_errors.py` (59 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (17 entity assertions; MatchScoreBreakdown correctly omits updated_at/version), `factories.py`, `constants.py`, `test_users.py` (shared constants + per-instance builders for all 6 entity-backed roles), `fixtures.py` (full lifecycle chains: registration → MATCHES_RUNNING with inspections, qualified-team via CHAIRMANS interview cascade, 24-team alliance-selection draft, and CLOSED-event waterfall; identity threading uses mentor/judge Person ids throughout), `__init__.py` barrel.

## Stage-2 self-check results
- 67/67 tests parse (`py_compile` clean across both directories).
- Tag audit: 67/67 docstrings end with exactly one valid `Design:` line; every tag resolves to a real instance with correct rule_id/section; every emitted difficulty instance has ≥2 tests, every emitted corner instance ≥1; skipped instances have zero tests.
- Citation audit: every test docstring contains a verbatim ≥8-word span that literally greps in PRD.md (automated sweep, 67/67 pass).
- No `skip`/`skipif`/`xfail` markers; no "scaffold" references in generated code.

(Orchestrator note: Steps 5 and 6 were launched concurrently in a single message. Post-completion verification: 67 test functions / 67 Design tags; py_compile clean.)

## Step 6: Generate implementation — 2026-08-10T23:42:00.000Z

Implementation complete. Summary:

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1132_robotics_competition_team_event_management/workspace/implementation/`:

- `start.sh` (executable, foreground via `exec`, `0.0.0.0:$PORT` default 10000, pip install guarded by `python3 -c "import flask"`)
- `requirements.txt` (flask>=2.2)
- `app.py` — Flask assembly, `ApiError`/404/405/400 handlers, request-scoped lock, blueprint registration
- `db.py` — in-memory dict store (17 entity tables), logical clock (default `2026-05-01T00:00:00Z`), UUID minting, ISO-8601 3-fractional-digit timestamps, `stamp_new`/`touch` (version+`updated_at`)
- `errors.py` — all 59 catalogued error IDs + `ApiError`
- `envelope.py` — `meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more` pagination (default 10, min 1, max 100), 400 on bad pagination
- `auth.py` — `X-User-ID`/`X-User-Role` validation (400) + per-endpoint role check (403) before any lookup
- `util.py` — body validators, left-to-right scoped path resolvers with per-segment 404 IDs, posture gate, `ERR_INVALID_STATE` vs `ERR_ALREADY_TERMINAL` state checks
- `services.py` — all 11 calculations: `score_match` (provisional/final card variants, floor 0), `ranking_points` (strict > 25/20 bonus thresholds), `team_ranking_score` (chronological pinned, FINALIZED-only, 4dp ROUND_HALF_UP via Decimal; forward_looking variant for projected-ranking), `generate_match_schedule` (ceil(N/6)×8 rounds, deterministic team_number/created_at ordering, ≥300 s same-field intervals, round-robin fields), `seed_alliance_captains` (top 8), snake-draft pick order, `award_winner_selection` (interview-mean / SAFETY fewest-open-violations / ROOKIE / default branches), `event_posture` (3-critical FROZEN), marginal `travel_reimbursement` (per-tier rounding, mode caps), championship waterfall (4 buckets), step `screening_expiry`
- `routes/events.py`, `registration.py`, `procurement.py`, `matches.py`, `alliances.py`, `awards.py`, `flat.py`

## Endpoints

**134 implemented / 134 declared** — verified by programmatic diff of the Flask URL map against the PRD §4 table (0 missing, 0 extra), including all 37 flat FK-reachability routes and `POST /_clock/set_current_utc`.

## Verification

- All 16 `.py` files pass `python3 -m py_compile` (cleaned `__pycache__` first)
- Two end-to-end smoke suites passed against live boots: full event lifecycle (SETUP→…→MATCHES_RUNNING), 8-team registration with screening OCC/segregation, part-order lifecycle + segregation, robot inspections incl. overweight gate, schedule generation (16 matches), queue/take-field/score/finalize (provisional 100→final 90 with YELLOW card, RP 4-0), replay, posture OPEN→RESTRICTED→FROZEN transitions and write-gating, snake-draft seeding + pick eligibility/turn-order, CHAIRMANS interview→decide cascade, marginal travel reimbursement (250000→185000), cap/`NOT_QUALIFIED` gates, clock-advance expiry, pagination guards
- Cold-boot isolation confirmed: fresh process starts with empty store (`total_count: 0`)

## Notable interpretation decisions (PRD-ambiguous points)

- **FROZEN gate exemption**: violation create/ack/resolve/escalate are exempt from the FROZEN write block so a frozen event can be remediated (PRD §1: "lock out downstream work *until the ripple is resolved*" — otherwise FROZEN is a deadlock).
- **OCC fields optional-when-omitted** (per skill guidance): `expected_person_version`/`expected_round_version`/`expected_event_version` are checked only when present; all validations run before any write (a 412-rejected `start-matches` commits nothing).
- Ephemeral qualification alliances carry `seed=None` and are excluded from selection logic (eligibility, sealing) so generated matches don't poison the draft.
- Unspecified error codes filled with nearest catalogue entry (e.g. missing STUDENT at roster submit → 422, missing-rounds/breakdown flat 404s → umbrella `ERR_NOT_FOUND`).

(Orchestrator route-parity check before sweep: extracted 134 (method, path) pairs from SCAFFOLD.yaml and diffed against the Flask url_map — 134/134 match, 0 missing, 0 extra.)

## Step 7: Run tests and iterate — 2026-08-11T00:00:00.000Z

**Summary**

- **Iterations run**: 2 (sweep 1: 60/67 in all 8 rounds, 7 deterministic failures; sweep 2 after fixes: 67/67 in all 8 rounds — clean).

- **Tests deleted**: none. All 7 failing tests traced to verbatim PRD rules with uniquely derivable outcomes.

- **Fixes applied to `test_helpers/`** (`/home/ubuntu/github/CodingPRD/tasks/task_1132_robotics_competition_team_event_management/test_helpers/fixtures.py`):
  - Added `_list_all` offset-pagination helper — PRD §2.3 caps `limit` at 100, but a 24-team event generates 128 matches / 264 alliances, so single-page `limit=100` listing silently truncated the slate (root cause of the four `ERR_MATCHES_OPEN` setup failures).
  - `_finalize_generated_schedule`, `next_safe_match_time`, `list_all_teams` now paginate via `_list_all`.
  - Added `list_selection_alliances` (paginates, then filters to alliances with non-null `seed`, matching PRD §3.6's 8 seeded captain rows vs. schedule-generated seed-less alliances); used in `setup_alliance_selection`, `run_full_snake_draft`, and `setup_closed_event_with_chairmans`.

- **Fixes applied to `test_suite/`** (`/home/ubuntu/github/CodingPRD/tasks/task_1132_robotics_competition_team_event_management/test_suite/test_05_replay_and_ranking.py`): `test_scored_match_replayed_and_new_match_reenters_cycle` now calls `complete_open_reset_log(ctx, m1["id"])` after replaying m1 — PRD §3.5 requires the prior FieldResetLog COMPLETE before the next take-field on the same field and explicitly permits completing it while the parent match is `REPLAYED`; the test's setup previously left the score-time reset log `IN_PROGRESS`.

- **Fixes applied to `implementation/`**:
  - `routes/procurement.py` — added the missing `gate_posture(event)` check to the four violation write endpoints (`create_violation`, `ack_violation`, `resolve_violation_endpoint`, `escalate_violation`), placed after path existence resolution and before state-machine checks per the PRD §2.7 priority ladder. PRD §2.6 states verbatim: "Any write attempted while posture is `FROZEN` is rejected with `ERR_EVENT_FROZEN` (HTTP 409)" — the generator's self-imposed violation-route exemption had no PRD basis (fixes `test_three_critical_violations_freeze_posture`).
  - `routes/matches.py` — `create_match` now enforces the field-interval rule: any existing match on the same event+field within strictly less than 300 s of the new `scheduled_at` is rejected with `ERR_FIELD_INTERVAL_VIOLATION` (HTTP 422). PRD §2.5 states the global invariant ("no two consecutive matches on the same field may be scheduled closer than this") and §3.4 pins the error; manual creation is the only write path that sets `scheduled_at` outside the self-satisfying generator (fixes `test_299_seconds_apart_rejected`; `test_300_seconds_apart_accepted` confirms the inclusive boundary).

(Orchestrator verification after exit: all 8 `results.{1..8}.json` files on disk, each reporting passed=67 total=67 failed=0.)

## Step 8: Finalize PRD — 2026-08-11T00:08:00.000Z

`/home/ubuntu/github/CodingPRD/tasks/task_1132_robotics_competition_team_event_management/workspace/PRD_FINALIZED.md` exists on disk. The diff against PRD.md is exactly five in-place revisions across four paragraphs; all other prose is verbatim.

## Line counts and delta
- PRD.md: 510 lines; PRD_FINALIZED.md: 510 lines; **0.0% line-count delta** (all edits are inline sentence revisions/insertions within existing paragraphs; no new sections).

## Changes (one bullet per edit)
- **§3.4** — revise — "acknowledges it (`OPEN → ACKED`) with no preconditions" → "with no additional preconditions", and appended a sentence pinning that all four violation writes (open/ack/resolve/escalate) are ordinary writes under the §2.6 posture gate, rejected with `ERR_EVENT_FROZEN` (409) while `FROZEN`, with the check after path resolution and before state-machine checks — `implementation/routes/procurement.py:362, 415, 428, 444` (Step 7's added `gate_posture(event)` calls).
- **§3.5** — insert — schedule-generator paragraph now states the generator persists two ephemeral `Alliance` rows per match (`seed` null, `FORMING`, members on captain/pick1/pick2, referenced by `red_alliance_id`/`blue_alliance_id`, visible via alliance list/get), and that all §3.6 selection rules plus the §3.2 disqualification cascade consider only `seed`-non-null alliances — `implementation/services.py:76-79` (`selection_alliances`), `services.py:315-327` (`_create_ephemeral_alliance`).
- **§3.5** — insert — manual-creation paragraph now enforces the field-interval invariant on `create_match`: any existing same-event/same-`field_index` match (either series, any status) with `scheduled_at` strictly <300 s away in either direction → `ERR_FIELD_INTERVAL_VIOLATION` (422); exactly 300 s accepted; check fires after duplicate-`match_number` and alliance-existence checks — `implementation/routes/matches.py:96-108`.
- **§3.2** — revise — disqualification cascade's alliance-slot clearing scoped from "any `Alliance` still in `FORMING`" to "any `Alliance` with a non-null `seed` still in `FORMING`" — `implementation/routes/registration.py:60-69, 238-245` (`_team_memberships_on_forming_alliance` skips `_ephemeral` ⟺ seed-null alliances).
- **§3.6** — revise — pick-eligibility's not-on-another-alliance condition scoped to alliances "whose `seed` is non-null" — `implementation/services.py:394-404` (`is_pick_eligible` iterates `selection_alliances`).

Step 7 items requiring no edit: the `_list_all` pagination helper (PRD §2.3 already fully pins limit≤100/`has_more` — pure fixture bug) and the `complete_open_reset_log` test fix (PRD §3.5 already permits completing a reset log while the parent match is `SCORED`/`FINALIZED`/`REPLAYED`).

## Per-edit pre-edit search log
1. **§3.4 violation posture edit.** (a) Subject: posture gating of violation write endpoints. (b) Enumerated: all four violation writes (`procurement.py` create 357-382, ack 409-419, resolve 422-435, escalate 438-451); global `gate_posture` sweep across every route file (`grep gate_posture`: 40+ call sites — every write endpoint is gated, none exempt); the internal violation created by `fail_robot_inspection` (procurement.py:334-343 — a cascade inside an already-gated endpoint, not one of "the four violation writes"); §2.6/§2.7's own claims. (c) Wording adjustment: chose "no additional preconditions" (mirroring §3.3's part-order rejection phrasing) plus an explicit sentence scoped to the four writes, avoiding any claim about reads or the inspection-fail cascade; deliberately did not touch §3.2 withdraw's similar "no preconditions" phrase (out of step_7_diff scope).
2. **§3.5 ephemeral-alliance insert.** (a) Subject: existence and seed-null semantics of schedule-generated alliances. (b) Enumerated: `_create_ephemeral_alliance` (services.py:315-327), `selection_alliances` and all consumers (`snake_seed_order` 373, `picks_made_in_round` 381, `current_captain_for` 386, `is_pick_eligible` 394, `seal_forming_alliances` 407, pick endpoint alliances.py:131-159), manual `create_alliance` (alliances.py:42-63, requires seed≥1 → unaffected), alliance list/get (alliances.py:66-82; flat.py:259-291 — ephemeral rows are returned, hence the "visible" clause), disqualify cascade (registration.py:60-69), waterfall CHAMPION lookup (services.py:503 — seed-filtered but behaviorally vacuous since nothing transitions ephemeral alliances out of `FORMING`; verified by grep that no code sets `CHAMPION`/`ELIMINATED` outside `util.py` terminal table). (c) Wording adjustment: phrased the member recording without claiming member-to-slot order; explicitly enumerated sealing and round completion in the carve-out so §3.6's "every `FORMING` alliance flips to `SEALED`" sentences (left verbatim) reconcile to seeded-only; did not pin the impl's fully-populated sealing condition (out of scope).
3. **§3.5 manual create_match interval edit.** (a) Subject: field-interval enforcement and its in-endpoint check ordering. (b) Enumerated: `create_match` full check sequence (matches.py:73-128 — role → event → posture → body → field_count → duplicate-number → alliance existence → interval); `generate_match_schedule` (services.py:267-312 — self-satisfies via `slot_seconds = max(cycle*60, 300)`, never rejects, so the rejection wording is scoped to manual creation); confirmed via grep that no other write path sets `Match.scheduled_at`; boundary semantics (`abs() < 300` rejects, 300 accepted) cross-checked against the diff note on `test_300_seconds_apart_accepted`. (c) Wording adjustment: added "of either series and regardless of that match's status" (impl has no series/status filter on this check) and the ordering clause "fires after the duplicate-`match_number` rejection and the alliance-existence resolutions" so the new sentence cannot be read through §2.7's ladder (15 < 21) into an order the impl does not exhibit.
4. **§3.2 disqualify scoping edit.** (a) Subject: which `FORMING` alliances the disqualify cascade clears. (b) Enumerated: `_team_memberships_on_forming_alliance` (registration.py:60-69 — skips `_ephemeral`, and the set of non-ephemeral alliances is exactly the seed-non-null set since manual creation requires seed≥1 and captain seeding assigns 1-8); disqualify caller (registration.py:238-245); withdraw (no alliance handling — untouched); `seal_forming_alliances` (only seeded alliances can leave `FORMING`, so the scoping can never strand a cleared slot on a sealable alliance). (c) Wording adjustment: used "with a non-null `seed`" rather than "non-ephemeral" so the criterion is expressible in public fields only (`_ephemeral` is an internal flag stripped by `public()`).
5. **§3.6 pick-eligibility scoping edit.** (a) Subject: which alliances block pick eligibility. (b) Enumerated: `is_pick_eligible` (services.py:394-404 — iterates `selection_alliances` with status `FORMING`/`SEALED`); pick endpoint call site (alliances.py:116-117); confirmed manual seed-non-null alliances still block (consistent with the new wording); confirmed no other endpoint consumes the eligibility predicate. (c) Wording adjustment: appended "whose `seed` is non-null" to the existing clause rather than rewriting the three-condition sentence, keeping the `CONFIRMED`/not-captain conditions verbatim.

## Step 9: Complete PRD — 2026-08-11T00:26:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1132_robotics_competition_team_event_management/workspace/PRD_COMPLETED.md` exists on disk.

## Summary

**Scale of change**: PRD_FINALIZED.md (source) 510 lines / 80,530 chars → PRD_COMPLETED.md 512 lines / 89,312 chars (+2 lines, +8,782 chars). 44 diff hunks: 42 in-paragraph revisions, 2 line insertions (one bullet in §2.2, one row in §5). No new sections.

**Counts**: ambiguity-pins: 34; mismatch-revisions: 10.

**Changes** (section — insert|revise — ambiguity|mismatch — what changed — impl file:line):

- §2.2 — insert — ambiguity — unrouted paths → `ERR_NOT_FOUND` 404; unsupported method → `ERR_INVALID_REQUEST` 405 — app.py:38-44
- §2.3 — revise — ambiguity — non-integer limit/offset → `ERR_INVALID_REQUEST` 400; `created_at` ties broken by insertion sequence — envelope.py:58-94
- §2.4 — revise — mismatch — OCC fields are optional-when-present (non-integer → 400, mismatch → 412, absent → unchecked) instead of "requires" — events.py:69-75, registration.py:382-387, alliances.py:124-130
- §2.6 — revise — ambiguity — only writes exempt from posture gate are event creation and the clock endpoint — events.py:82-125,387-396
- §2.7 — revise — mismatch — example fixed (`TeamLead`→`RegistrationOfficer` calling confirm; role check at priority 2 fires first) — registration.py:170
- §2.7 — revise — ambiguity — body-validation `ERR_INVALID_REQUEST` unranked (fires where body is parsed); `breakdownId`/`roundId` resolve to generic `ERR_NOT_FOUND` 404 — util.py:205-209,233-237
- §2.8 — revise — ambiguity — list endpoints accept field equality filters; integer-backed filters reject non-integers with `ERR_INVALID_REQUEST` — flat.py:49-71
- §2.9 — revise — ambiguity — clock set is unconditional (no monotonicity), exempt from posture gate, runs expiry+posture recompute across all events, returns `{"current_utc": ...}`; logical clock drives all entity timestamps — events.py:387-396, db.py:80-101
- §3.1 — revise — ambiguity — duplicate `event_code` → `ERR_INVALID_REQUEST` 400; optional `budget_cap_cents` accepted at creation (no cap enforced when omitted) — events.py:96-122
- §3.1 — revise — mismatch — `window_minutes` defaults to 0; nonzero for point-in-time kinds is rejected (`ERR_INVALID_REQUEST`), not "recorded as 0" — events.py:334-342
- §3.1 — revise — ambiguity — on mark-passed, posture gate fires before `milestoneId` resolution — events.py:373-377
- §3.1 — revise — ambiguity — open-registration capacity failure → `ERR_INVALID_REQUEST` 400 — events.py:161-162
- §3.2 — revise — ambiguity — team creation not gated on event status; optional `is_rookie` boolean — registration.py:77-104
- §3.2 — revise — ambiguity — roster student check fails with `ERR_INVALID_REQUEST` at HTTP 422 — registration.py:161-163
- §3.2 — revise — ambiguity — email validated by simplified shape (local@dotted-domain, no whitespace); duplicate/malformed → `ERR_INVALID_REQUEST` 400; unknown `team_id` → `ERR_TEAM_NOT_FOUND` — registration.py:57,264-272
- §3.2 — revise — ambiguity — screening submission requires person `PENDING` (`ERR_INVALID_STATE`/`ERR_ALREADY_TERMINAL`); wrong event status → `ERR_EVENT_WRONG_STATUS` — registration.py:324-327
- §3.2 — revise — mismatch — approve OCC is optional (per §2.4 revision); reject sets `decision` `REJECT`; both decision calls return the updated `Person` — registration.py:365-413
- §3.2 — revise — mismatch — disqualify cancels only `PROPOSED`/`CONFIRMED` interview slots, not "every" slot — registration.py:233-236
- §3.3 — revise — ambiguity — part-order creation not gated on event status (BUILD_SEASON applies at submission) — procurement.py:64-88
- §3.3 — revise — ambiguity — submit: missing STOP_BUILD → `ERR_MILESTONE_MISSING`; earliest of multiple STOP_BUILD `scheduled_at` is deadline; non-CONFIRMED team → `ERR_INVALID_STATE` 409 — procurement.py:122-129
- §3.3 — revise — ambiguity — budget cap is event's `budget_cap_cents` (absent → no check); approved spend sums `APPROVED`/`VENDOR_PLACED`/`RECEIVED` orders — procurement.py:149-157
- §3.4 — revise — ambiguity — unresolvable `inspector_id` → `ERR_PERSON_NOT_FOUND` 404 — procurement.py:233-235
- §3.4 — revise — ambiguity — inspection submit outside INSPECTION → `ERR_EVENT_WRONG_STATUS` — procurement.py:276-277
- §3.4 — revise — mismatch — inspection submit flips team `robot_inspection_status` `NOT_SUBMITTED → SUBMITTED` (PRD claimed "no side effects") — procurement.py:291-293
- §3.4 — revise — ambiguity — fail-created violation's `opened_by_person_id` is the LeadInspector's `X-User-ID` — procurement.py:334-341
- §3.4 — revise — mismatch — `WAIVED` is a reserved value no endpoint sets (PRD claimed "operational exception paths"); accepted everywhere `PASSED` is — services.py:261, events.py:226
- §3.4 — revise — ambiguity — violation `opened_by_person_id` must resolve to a Person of the event (`ERR_PERSON_NOT_FOUND`) — procurement.py:368-370
- §3.4 — revise — ambiguity — escalating non-CRITICAL → `ERR_INVALID_STATE` 409 — procurement.py:446-447
- §3.5 — revise — mismatch — start-matches requires posture `OPEN` (not merely non-FROZEN); unresolved-CRITICAL surfaces as `ERR_EVENT_FROZEN`; pinned in-call check order (status → posture → inspection → critical → team-count → OCC) — events.py:217-246
- §3.5 — revise — ambiguity — generator mechanics: floor(N/6) matches per round, rotation offset 6r mod N, sequential `match_number` from 1, base time = event `start_date`, slot gap = max(cycle×60, 300)s, fields rotate 1..field_count — services.py:267-312
- §3.5 — revise — ambiguity — manual create: out-of-range `field_index` → `ERR_INVALID_REQUEST` 400; alliance ids resolve else `ERR_ALLIANCE_NOT_FOUND`; not gated on event status — matches.py:73-108
- §3.5 — revise — ambiguity — queueing at wrong event status → `ERR_EVENT_WRONG_STATUS` — matches.py:165-166
- §3.5 — revise — ambiguity — queue-slot create: unknown team → `ERR_TEAM_NOT_FOUND`; duplicate position → `ERR_INVALID_REQUEST` 400; not gated on match status — matches.py:340-364
- §3.5 — revise — mismatch — take-field blocked only by an `IN_PROGRESS` reset log on the field (`COMPLETE`/`ABORTED`/none all pass; PRD said "must be COMPLETE or nonexistent") — matches.py:191-203
- §3.5 — revise — ambiguity — breakdowns attachable only in `SCHEDULED`/`QUEUED`/`ON_FIELD` (terminal → `ERR_ALREADY_TERMINAL`; `SCORED`/`REPLAYED` → `ERR_INVALID_STATE`); duplicate color → `ERR_INVALID_REQUEST` 400; `tech_foul_count` non-negative — matches.py:289-321
- §3.5 — revise — ambiguity — zero-counted-match teams aggregate to 0.0000/0.0000/0 — services.py:229-234
- §3.5 — revise — ambiguity — replay grounds = a `MATCH_REVIEW` violation against any of the six participating teams, any `resolution_status` — matches.py:269-275
- §3.5 — revise — mismatch — match-cancel cascade comes from `DISQUALIFIED` only; withdrawal does not cancel matches (PRD said "DISQUALIFIED or WITHDRAWN") — registration.py:186-208 vs 226-232
- §3.6 — revise — ambiguity — manual alliance create takes `seed` (≥1) + `captain_team_id` (resolvable, else `ERR_TEAM_NOT_FOUND`), born `FORMING` — alliances.py:42-63
- §3.6 — revise — mismatch — sealing flips only fully-populated `FORMING` alliances (not "every Alliance still in FORMING"); completed round's `current_captain_team_id` → null — services.py:407-415, alliances.py:145-148
- §3.6 — revise — ambiguity — pick requires event `ALLIANCE_SELECTION` (`ERR_EVENT_WRONG_STATUS`), unknown picked team → `ERR_TEAM_NOT_FOUND`, response carries the updated round — alliances.py:101-163
- §3.7 — revise — ambiguity — slot propose: unknown team/judge → `ERR_TEAM_NOT_FOUND`/`ERR_PERSON_NOT_FOUND`; non-JUDGE judge → `ERR_INVALID_REQUEST` 400; judge `CLEARED` screening enforced at completion, not proposal — awards.py:150-180, 248-250
- §3.7 — revise — ambiguity — confirm ownership failure → `ERR_UNAUTHORIZED_ROLE` 403 — awards.py:217-220
- §3.7 — revise — ambiguity — complete by wrong judge or non-CLEARED judge → `ERR_UNAUTHORIZED_ROLE` 403 — awards.py:239-251
- §3.7 — revise — ambiguity — no-show: wrong judge → `ERR_UNAUTHORIZED_ROLE` 403; clock must be strictly past window end, else `ERR_INVALID_STATE` 409 — awards.py:273-288
- §3.7 — revise — ambiguity — SAFETY severity weights pinned: MINOR 1, MAJOR 2, CRITICAL 3 — services.py:44
- §3.7 — revise — ambiguity — begin-judging/present at wrong event status → `ERR_EVENT_WRONG_STATUS` 409 — awards.py:96-97, 137-138
- §3.8 — revise — ambiguity — close-event with outstanding violations → `ERR_INVALID_STATE` 409 — events.py:310-312
- §3.8 — revise — ambiguity — booking creation not gated on qualification (checked at approval); zero-reimbursement approval → `ERR_INVALID_REQUEST` at HTTP 422 — procurement.py:462-482, 514-521
- §3.8 — revise — mismatch — reimbursement cap enforced at approval time, not "validation time" — procurement.py:516-518
- §3.9 — revise — mismatch — cascade bullets aligned: disqualify cancels only PROPOSED/CONFIRMED interview slots; match-cancel cascade is disqualify-only; inspection submit flips team status; clock advance runs expiry globally and recomputes all postures — registration.py, procurement.py, events.py:387-396
- §4 — revise — ambiguity — non-OCC endpoints ignore (not reject) stray version fields — util.py:54-61
- §5 — insert — ambiguity — added `ERR_NOT_FOUND | 404` row; noted the three non-400 `ERR_INVALID_REQUEST` sites (405, 422, 422) — errors.py:14, app.py:44, registration.py:163, procurement.py:521

(Orchestrator verification after exit: `workspace/PRD_COMPLETED.md` on disk, 512 lines / 89,312 bytes.)


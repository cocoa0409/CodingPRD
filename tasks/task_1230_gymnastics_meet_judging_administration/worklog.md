# Worklog — task_1230_gymnastics_meet_judging_administration

## Step 1: Create Task Directory — 2026-08-12T03:00:00.000Z

Pre-assigned output folder `tasks/task_1230_gymnastics_meet_judging_administration` with `workspace/` subdirectory already exists; Step 1 auto-index scan skipped per instructions. Difficulty parameter: "generate task hard than expert level!".

## Step 2: Generate Scaffold — 2026-08-12T03:22:00.000Z

Generated the three scaffold artifacts for task_1230 Gymnastics Meet & Judging Administration at harder-than-expert difficulty.

**Output files (absolute paths):**
- `/home/ubuntu/github/CodingPRD/tasks/task_1230_gymnastics_meet_judging_administration/SCAFFOLD.yaml` — 109,542 bytes
- `/home/ubuntu/github/CodingPRD/tasks/task_1230_gymnastics_meet_judging_administration/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 68,658 bytes
- `/home/ubuntu/github/CodingPRD/tasks/task_1230_gymnastics_meet_judging_administration/SCAFFOLD_CORNER_DESIGN.yaml` — 42,819 bytes

**Final counts:**
- Entities: 17 (Meet, Session, Squad, Gymnast, AthleteEntry, Coach, CoachMeetPass, Judge, JudgePanel, PanelAssignment, Rotation, WarmupBlock, Score, Inquiry, Award, SpectatorTicket, QualificationRecord)
- State machines: 10 (Meet, Session, Rotation, Score, Inquiry, CoachMeetPass, PanelAssignment, AthleteEntry, SpectatorTicket, QualificationRecord) — includes cyclic (Inquiry FILED↔UNDER_REVIEW), branching (Score inquiry fork), and compound/posture-driven (Meet.posture)
- Endpoints: 96 (including `_clock/set_current_utc` for temporal determinism)
- Errors: 33 (3 OCC-specific 412 codes + safety/temporal/constraint/referential/fiscal categories)
- Roles: 6 (MeetDirector, MeetReferee, JudgePanelChief [entity_backed:Judge], Coach [entity_backed:Coach], GateAttendant, Spectator) — segregation_of_duties model
- Calculations: 10 (provisional_score, final_score, all_around_total, award_ordering, ceremony_ordering, qualification_evaluation, squad_assignment, judge_panel_selector, rotation_temporal_layout, warmup_block_layout)
- Validations: 25 across 8 priority categories
- Concurrency rules (OCC): 3

**Difficulty design instances: 18** (2 per rule × 9 rules — dual_variant_calc, combinatorial_formula [modes (a) and (c)], non_linear_state_machine [cyclic + branching], transitive_cascade [depth-3 × 2 from different triggers], priority_pair_validation_conflict [state×state + safety×temporal], boundary_precision_check [numeric threshold + temporal deadline], cross_entity_state_dependency [Rotation→JudgePanel + Score→Rotation], resource_temporal_overlap [half-open vs closed/shared-boundary interval semantics], compensating_invariant [FINAL-sum conservation + delta-neutrality identity])

**Corner design instances: 33** (31 with full test_recipe + 2 `excluded_because` stubs) covering entities, state_machines, calculations, validations, endpoints, errors, RBAC, cross-cutting layers, and consistency model sections per the claim-extraction guide taxonomy.

**Lint verdict:** `clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

**Key structural choices for harder-than-expert difficulty:** hybrid topology with cross-aggregate FKs; posture-driven gating (Meet.posture gates all child mutations); dual-variant score calculation (publish-time vs post-inquiry); 3-variant qualification rule with boundary-precise >= comparisons; USAG_CLASSIC vs NCAA_MODIFIED tie-break policies producing divergent award ordering; waterfall warm-up allocation with remainder pinning to last squad; cascade chains of depth 3 (scratch → Score.VOID → Squad.athlete_count → PanelAssignment.conflict_flag; pass suspension → Inquiry.EXPIRED → Score.PUBLISHED); OCC on three different parents (Score, Inquiry, Session); per-apparatus judge-count rules (BB/FX=4 vs VT/UB=2) driving panel-staffing selector.

## Step 3: Copy Shared Files — 2026-08-12T03:23:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1230_gymnastics_meet_judging_administration/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-12T03:45:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1230_gymnastics_meet_judging_administration/workspace/PRD.md` (381 lines). The withheld difficulty/corner index files were never opened; no sibling tasks were inspected.

**Section list**
- §1 Introduction (2 paragraphs — meet-operations pain points + design centers)
- §2 Global Specifications: 2.1 RBAC (6 roles, `X-User-ID`/`X-User-Role`, per-role identity translations), 2.2 API Response Structure (verbatim — byte-match verified against `section-2.2-response-structure.md`), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending, all per-list filter params enumerated), 2.4 Logical Clock (startup default 2026-05-01T00:00:00Z, `to_iso8601`, never wall-clock), 2.5 Meet Posture as Master Gate, 2.6 Common Resource Properties, 2.7 Score Precision (3dp half-up, ranges, 0.000 floor), 2.8 OCC (3 rules), 2.9 Validation Order (priority chain as ordered prose), 2.10 Nested Resource Retrieval
- §3 Business Logic (9 subsections): 3.1 Meets/Sessions/Timetable, 3.2 Rosters/Entries/Squad Assignment, 3.3 Coach Credentialing & Floor Access, 3.4 Judge Panels & COI, 3.5 Rotations/Warm-Up Blocks/Meet-Day Flow, 3.6 Score Entry/Publication/Inquiry, 3.7 Session Close-Out/Awards/Ceremony Order, 3.8 Qualification, 3.9 Spectator Admission & Live Display
- §4 Endpoint Definitions — 96 rows (4 columns only)
- §5 Error Code Catalogue — 33 rows (2 columns only)

**Coverage counts**: 17 entities (114 field names), 96 endpoints (76 request-input identifiers, 1 path param `id`), 33 errors (all mentioned in §2/§3 prose), 12 state machines (10 explicit + JudgePanel/WarmupBlock via cascade narratives), 10 calculations, 25 validations, 3 OCC rules.

**Hard contract reports**
```
Field coverage check:
- entities[].fields: 114 required, 114 present, 0 missing
- endpoints[].request_body: 76 required, 76 present, 0 missing
- endpoints[].path_params (+occ fields, query params, flight_count): 4 required, 4 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 25 checked, 25 expressed (§2.9 orders the full chain + per-endpoint orderings), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (endpoint + expected_*_version + ERR_STALE_* + 412), 0 missing
- state_machines[].transitions: 52 checked, 52 fully expressed (from/to, preconditions, side effects), 0 missing
- calculations[]: 10 checked, 10 fully expressed (thresholds, formulas, rounding order, variants), 0 missing
- validations[] conditions: 25 checked, 25 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 96 / 25 checked, expressed in workflow narratives, 0 missing
- entities[].fields[] structured content: 114 checked, defaults/ranges/formats/null-until semantics reconstructible, 0 missing
- sibling-branch symmetry: 6 groups (3 scratch sources, UPHELD/DENIED, withdraw/expire, 2 tie-break policies, 3 qualify-rule variants, ticket exits), equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 603
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Scaffold-to-PRD translation notes**
- Regex constraints were rendered as prose ("the uppercase letter A followed by exactly seven digits"; "the literal prefix USAG-, four digits, a hyphen, four digits").
- Validation `applies_to` scopes naming endpoints absent from the endpoint table (e.g., single-rotation create, session update, single-entry squad assign, panel activate) were expressed in business terms ("declared one at a time or generated as a set", "at creation or by a later update") to preserve Contract 3 without inventing endpoints in §4.
- WarmupBlock/JudgePanel have no explicit state-machine entries; their state progressions were reconstructed strictly from cascade side-effects in the Session/Rotation/Meet machines (SCHEDULED→IN_PROGRESS→COMPLETE/SKIPPED; FORMING→FULL→ACTIVE→RELEASED).
- Scratch sibling asymmetry was preserved deliberately: conflict-flag recomputation only for pre-competition scratches, non-DRAFT score retention only for mid-competition scratches.
- `ERR_INVALID_REQUEST` and `ERR_ALREADY_TERMINAL` (catalog-only, not in validations[]) were homed in §2.6; `ERR_INQUIRY_ALREADY_OPEN` in the filing narrative.
- Two field names (`score_id`, `session_id`) needed a second coverage pass and were added inline in §3.6/§3.2.

## Step 5: Generate Unit Tests — 2026-08-12T04:16:00.000Z

## Generation Summary — task_1230_gymnastics_meet_judging_administration

**Output locations**
- `/home/ubuntu/github/CodingPRD/tasks/task_1230_gymnastics_meet_judging_administration/test_helpers/` — 9 files: `__init__.py` (barrel), `types.py` (17 entity TypedDicts, 15 status/role enums; all entities carry full common fields), `api_client.py` (74 endpoint methods covering the full PRD §4 surface incl. `set_clock`), `api_errors.py` (33 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py`, `factories.py` (unique-number counters per entity), `constants.py` (rotation pace, changeover gap, warmup window, panel counts, qualification thresholds), `test_users.py` (shared constants for opaque roles + `make_coach_headers`/`make_judge_panel_chief_headers` per-instance builders for entity-backed roles), `fixtures.py` (composite flow: `setup_competition_ready` builds meet→session→squad→entries→credentialed coach+floor pass→12 judges→4 staffed panels→published meet→generated rotations→clock advance; plus `setup_published_score`, `setup_filed_inquiry`, `setup_inquiry_under_review`, `run_rotations_with_scores`, `close_session`, `setup_closed_session`, `setup_archived_meet`, `setup_squads_for_layout`).
- `test_suite/` — `conftest.py` + **8 test files, 66 test functions** (test_01 meet lifecycle, test_02 rosters/entries/squads, test_03 rotations/warmup, test_04 judge panels, test_05 scores, test_06 inquiries, test_07 session-close/awards/qualification, test_08 tickets/spectators/auth).

**Queue A (Difficulty) — 18/18 instances, 2 tests each (36 tests)**, including the heavy flows: full four-rotation closed sessions for award tie-break chains (shared-rank skip place 2,2,4) and qualification thresholds (32.000 inclusive vs 31.999), dual-variant provisional-vs-final recompute (13.950 → 14.500), inquiry review loops with relative version arithmetic, pass-suspend/revoke → inquiry EXPIRED → score PUBLISHED cascades, and OCC-stale publishes.

**Queue B (Corner) — 30/31 non-stub instances translated (30 tests)**; both `excluded_because:` stubs (`error_inquiry_window_expired_covered`, `error_judge_conflict_of_interest_covered) verified to resolve to real queue-A instances and not translated.

**Skipped (1, PRD-first filter):** `Corner/calculations/all_around_total_with_void_apparatus_excluded` — its asserted AA==40.800 requires `all_around_total` to be computed for an entry scratched from COMPETING, but the PRD defines the completion computation only on the COMPETING→COMPLETED transition, which a SCRATCHED entry never reaches; two PRD-faithful readers diverge, so the instance fails unique derivability.

**Deliberate weakenings within translated instances** (silence-pattern compliance, not skips): initial `version == 1` dropped from meet defaults (unstated); "caller cannot override provisional_total" dropped (mass-assignment not covered); `conflict_flag` flip-on-scratch dropped (whether SCRATCHED entries count as "entered" is ambiguous); selector filter-ordering not asserted (unobservable); late-inquiry filing uses `validate_error_is_one_of([ERR_INQUIRY_WINDOW_EXPIRED, ERR_INVALID_STATE])` (error-precedence pattern — the auto-finalize quiet path races the window check); archived-meet mutations use `is_one_of([ERR_ALREADY_TERMINAL, ERR_INVALID_STATE])`.

**Verdicts:** py_compile OK; pyflakes clean; coverage audit pass (18/18 ×≥2, 30/31 ×≥1, stubs untranslated); verbatim citation audit pass (95/95 quoted citations grep-verified against PRD.md); C4 audit pass (every docstring ends with exactly one resolving `Design:` line; 66 tags = 66 tests); zero `skip`/`skipif`/`xfail` markers.

## Step 6: Generate Implementation — 2026-08-12T04:16:00.000Z

All done. Final state verified: compiles clean, 185 smoke checks green across three fresh-boot runs, and the store is confirmed empty on restart.

**Implementation location:** `/home/ubuntu/github/CodingPRD/tasks/task_1230_gymnastics_meet_judging_administration/workspace/implementation/`

**File list (sizes):**
| File | Size | Role |
|---|---|---|
| `start.sh` | 396 B (executable) | Guarded pip install (`if ! python3 -c "import flask"`), `exec python3 app.py` in foreground |
| `requirements.txt` | 11 B | `flask>=2.2` |
| `app.py` | 1,785 B | App factory, envelope-shaped error handlers, blueprint registration, `0.0.0.0:$PORT` (default 10000) |
| `common.py` | 14,723 B | In-memory store (17 dicts), logical clock (boots at 2026-05-01T00:00:00Z), envelope/pagination helpers, auth (`X-User-ID`/`X-User-Role`), field/score/delta validators |
| `logic.py` | 22,967 B | Clock-driven transition sweep (fixpoint), cascades, all calculations/selectors |
| `serialize.py` | 9,217 B | Per-entity wire serializers (ISO-8601 3-fractional-digit UTC, Decimal→float) |
| `routes_core.py` | 23,111 B | Meets, sessions, squads, gymnasts, athlete entries |
| `routes_people.py` | 17,189 B | Coaches, coach passes, judges, panels, panel assignments |
| `routes_scoring.py` | 26,535 B | Rotations, warm-up blocks, scores, inquiries |
| `routes_misc.py` | 18,884 B | Awards, spectator tickets, qualification records, live scores, clock endpoint |

**Endpoints:** exactly **96 (method, path) pairs** — the full SCAFFOLD.yaml §1.5 table; Flask's implicit `/static` route disabled so nothing extra is registered. (Orchestrator independently re-verified: 96/96 exact match, 0 missing, 0 extra.)

**Coverage:**
- **Entities:** all 17, with system fields `id`/`created_at`/`updated_at`/`version`, computed fields (posture, athlete_count, conflict_flag, provisional/final totals, ranks) maintained by transitions.
- **State machines:** all 10 (Meet, Session, Rotation, Score, Inquiry incl. the UNDER_REVIEW→FILED loop, CoachMeetPass, PanelAssignment, AthleteEntry, SpectatorTicket, QualificationRecord) plus Coach verify; time-driven transitions (warmup open, march-in, rotation warmup, block IN_PROGRESS→COMPLETE, inquiry-window self-finalization, 4×window inquiry expiry, rotation/session rollup, meet WARMUP_OPEN→IN_COMPETITION) fire off the logical clock via a fixpoint sweep on every request and clock set.
- **Calculations:** provisional/final score (3dp ROUND_HALF_UP via Decimal, floored at 0, after-inquiry delta recomputation), all-around (sum of FINAL finals), award ordering (USAG_CLASSIC E→D→deduction chain with shared-rank skipping; NCAA_MODIFIED immediate shared rank; `is_tied`/`tiebreak_rank`/`was_tiebroken`), ceremony ordering (`category_index*100 + max_place - place + 1`), qualification evaluation (all level thresholds, inclusive `>=`, ALL_AROUND_ONLY/PER_EVENT/BOTH with mobility-score pinning, PROVISIONAL record generation), squad assignment (created_at FIFO, member-number tiebreak, gym cohesion, capacity cap, overflow left unassigned), judge panel selector (rating tiers, availability coverage, cross-panel temporal overlap, COI exclusion, `ERR_INSUFFICIENT_JUDGE_POOL`), rotation temporal layout (per-athlete pace, 5-min changeover), warmup waterfall layout (2 min/athlete clamped 8–20, remainder to last squad).
- **Validations:** priority chain auth(401)→role(403)→path existence(404, left-to-right)→body FK(404)→posture(409)→state(409, `ERR_ALREADY_TERMINAL` for terminal entities)→business rules in safety/temporal/constraint/referential/fiscal order; OCC `expected_score_version`/`expected_inquiry_version`/`expected_session_version` (400 if absent, 412 on mismatch); all 30 catalog error IDs emitted. Inquiry filing checks credentials before the window, and the window check precedes the terminal gate so `ERR_INQUIRY_WINDOW_EXPIRED` stays reachable after self-finalization.

**start.sh contract:** confirmed — binds `$PORT` (default 10000) on `0.0.0.0`, runs in foreground via `exec`, responds within seconds, dependency install guarded for per-test reboots, and every boot starts with an empty store (verified: `GET /meets` returns `total_count: 0` on a fresh process). No seeding, no disk persistence anywhere.

## Step 7: Run Tests and Iterate — 2026-08-12T04:25:00.000Z

All 8 rounds pass 66/66. Clean sweep achieved.

**Iterations run:** 2 (initial sweep surfaced 5 unique deterministic failures; iteration 2 confirmed all fixes, 8/8 rounds green at 66/66).

**Tests deleted:** None.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1230_gymnastics_meet_judging_administration/test_helpers/fixtures.py` — `setup_competition_ready`: the `level_band` parameter was accepted but never forwarded into `create_session`, so sessions were always created at the factory default `L9` while gymnasts were created at the requested level (e.g. `L4`). Compulsory L4 requires exact band match, so setup died with `ERR_LEVEL_BAND_MISMATCH`. Fixed by injecting `level_band` into session overrides via `setdefault`. This single fixture bug accounted for 4 of the 5 failures (`test_all_around_exactly_32000_qualifies`, `test_all_around_31999_does_not_qualify`, `test_aa_only_vs_per_event_outcome_split`, `test_per_event_record_pins_event_score_and_threshold`) — consistent with the triage-hint pattern of one upstream fixture bug masquerading as many independent failures.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1230_gymnastics_meet_judging_administration/test_suite/test_02_rosters_entries_squads.py` — `TestCheckInPreconditions.test_check_in_requires_floor_access_granted`: PRD §3.2 states the floor-access precondition for check-in but names no error_id for its violation; §2.9 names both `ERR_INVALID_STATE` (entity state precondition) and `ERR_COACH_CREDENTIAL_LAPSED` (coach credential safety check) without pinning which fires for a not-yet-granted pass — fails unique derivability on the exact error_id. Relaxed the assertion to `validate_error_is_one_of([ERR_INVALID_STATE, ERR_COACH_CREDENTIAL_LAPSED])` (the permitted coverage correction) while keeping the uniquely-derivable assertions: the request is rejected and the entry remains `REGISTERED`. Added the `validate_error_is_one_of` import.

**Fixes applied to `implementation/`:** None — the implementation was already PRD-faithful on all exercised paths.

## Step 8: Finalize PRD — 2026-08-12T04:29:00.000Z

Done. PRD_FINALIZED.md is written with exactly one inline revision.

**Line counts:** PRD.md = 381 lines; PRD_FINALIZED.md = 381 lines (0.0% delta — one line revised in place, no lines added or removed).

**Changes (one bullet per change):**
- §3.2 — revise — the check-in sentence now names the error for the floor-access precondition violation: "provided the coach holds a pass with floor access granted on the parent meet (a coach who holds no such pass is rejected with `ERR_COACH_CREDENTIAL_LAPSED`, HTTP 422)" — `implementation/routes_core.py:506-511` (`check_in_entry` raises `ApiError("ERR_COACH_CREDENTIAL_LAPSED", 422, ...)` when no pass of the acting coach is `FLOOR_ACCESS_GRANTED` on the entry's meet).

**Step 7 items requiring no edit:**
- The `test_helpers/fixtures.py` `level_band` forwarding bug is a pure fixture bug: PRD §3.2 already uniquely pins compulsory exact band match ("for the compulsory levels `L2` through `L5` the gymnast's `competitive_level` must match the session's `level_band` exactly"), and §3.8 already pins the L4/L5 32.000 STATE threshold with inclusive boundary. The test factory default (`L9`) is test scaffolding, not implementation behavior. Nothing PRD-silent was revealed.

**Per-edit pre-edit search log:**

Edit 1 (§3.2 check-in sentence):
- (a) Subject: the "coach must hold a pass with floor access granted on the meet" precondition and the error_id its violation reports.
- (b) Impl paths enumerated and read: `implementation/routes_core.py:493-521` (check-in: terminal → `ERR_ALREADY_TERMINAL`; non-`REGISTERED` → `ERR_INVALID_STATE`; no granted pass → `ERR_COACH_CREDENTIAL_LAPSED` 422; gym mismatch → `ERR_UNAUTHORIZED_ROLE`; no expiry re-check at check-in); `implementation/routes_scoring.py:409-449` (inquiry filing: missing pass and lapsed expiries both → `ERR_COACH_CREDENTIAL_LAPSED`, already pinned by PRD §3.6); `implementation/routes_misc.py:375-401` (qualification decline: missing pass → `ERR_COACH_CREDENTIAL_LAPSED`; PRD §3.8 names no error there and my edit makes no claim about it); `implementation/routes_people.py:145-165` (grant-floor-access: non-`CREDENTIALED` → `ERR_INVALID_STATE`, lapsed expiries → `ERR_COACH_CREDENTIAL_LAPSED`, already pinned by PRD §3.3); `implementation/routes_people.py:187-204` (reinstate: lapsed expiries → `ERR_COACH_CREDENTIAL_LAPSED`, covered by §3.3). Also grepped all PRD "floor access"/"check-in" mentions (lines 160, 172, 174, 204, 230, 269, 279-281) to confirm no other sentence describes the check-in precondition.
- (c) Wording adjustment: kept the parenthetical scoped strictly to the check-in sentence and to the pass-state condition only — deliberately did not add "with both credential expiries still in the future" (as §3.6 does for inquiry filing), because the implementation does not re-check credential expiries at check-in (`routes_core.py:506-511` tests `pass_state == "FLOOR_ACCESS_GRANTED"` only). No universal claim about other floor-access-gated endpoints is made, so the §3.3/§3.6/§3.8 paths enumerated above all remain correctly described.

## Step 9: Complete PRD — 2026-08-12T04:38:00.000Z

Done. `PRD_COMPLETED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_1230_gymnastics_meet_judging_administration/workspace/PRD_COMPLETED.md`.

**Size delta:** PRD_FINALIZED.md 381 lines / 62,548 chars → PRD_COMPLETED.md 381 lines / 65,932 chars (+3,384 chars, 0 line-count change; all edits inline).

**Counts:** 17 ambiguity-pins, 7 mismatch-revisions (24 edited passages).

Changes (section — insert|revise — ambiguity|mismatch — what — impl ref):

- §2.6 — insert — ambiguity — uniqueness violations (meet name/year, sanction/member/coach/judge numbers, session & squad labels) pinned to `ERR_INVALID_REQUEST` (400) — routes_core.py:43-65,239-241,334-336,389-399; routes_people.py:29-40,232-234,244-247
- §2.8 — insert — ambiguity — OCC version match evaluated after the terminal gate, before state preconditions — routes_scoring.py:328-343,539-548; routes_core.py:293-300
- §3.1 — insert — ambiguity — publish rejected with `ERR_INVALID_STATE` (409) when a session has no squad — routes_core.py:124-127
- §3.1 — insert — ambiguity — close-scoring and finalize precondition failures pinned to `ERR_INVALID_STATE` (409) — routes_core.py:143-161,173-183
- §3.2 — revise — mismatch — `date_of_birth` "stored as UTC midnight" dropped (impl stores any timestamp) — routes_core.py:393, common.py:61-75
- §3.2 — insert — ambiguity — entry born with `all_around_total` 0.000, `all_around_rank` null, `qualified_for_next_meet` false — routes_core.py:460-471
- §3.2 — insert — ambiguity — band adjacency measured on the full 14-band ordering (L10 adjacent to XCEL_BRONZE) — common.py:417-420
- §3.2 — insert — ambiguity — check-in gym mismatch pinned to `ERR_UNAUTHORIZED_ROLE` (403) — routes_core.py:512-517
- §3.2 — revise — mismatch — entry completes once at least four scores are `FINAL`/`VOID` (not "all four apparatus scores") — logic.py:416-424
- §3.2 — revise — mismatch — removed the `ERR_SQUAD_CAPACITY_EXCEEDED` direct-assign sentence; no such endpoint exists, membership changes only via the selector — logic.py:441-478 (error never raised)
- §3.3 — insert — ambiguity — grant-floor-access with non-`CREDENTIALED` coach → `ERR_INVALID_STATE` (409) — routes_people.py:154-157
- §3.3 — revise — mismatch — suspend/revoke inquiry-expiry cascade scoped to inquiries on scores of this meet — routes_people.py:132-142
- §3.4 — insert — ambiguity — panel creation requires `meet_id` to equal the session's own meet — routes_people.py:297-299
- §3.4 — insert — ambiguity — auto-assign: rejected `ERR_INVALID_STATE` (409) if panel already has PROPOSED/CONFIRMED; top judge gets `PANEL_CHIEF`, rest `E_JUDGE`; returns created array — routes_people.py:342-347, logic.py:521-534
- §3.5 — insert — ambiguity — rotations numbered in session `apparatus_set` order — logic.py:547-548
- §3.5 — revise — mismatch — rotation overlap rule replaced: rotations only come from the generator; re-generation rejected with `ERR_ROTATION_OVERLAP` (422) — logic.py:539-542
- §3.5 — insert — ambiguity — warm-up block outside the 60-minute window → `ERR_WARMUP_BLOCK_OVERLAP` (422); block auto-resolves to `COMPLETE` at `block_end` (`SKIPPED` never assigned); block re-generation rejected with `ERR_WARMUP_BLOCK_OVERLAP` — routes_scoring.py:151-155, logic.py:366-369,569-572
- §3.5 — revise — mismatch — open-scoring: staffing check (`ERR_PANEL_UNDERSTAFFED`) evaluated first, then panel-`ACTIVE` and clock checks (`ERR_INVALID_STATE` 409) — routes_scoring.py:65-85
- §3.5 — revise — mismatch — close-scoring coverage rule: every squad-assigned non-`SCRATCHED` entry of the session needs a score in this rotation (gap → `ERR_INVALID_STATE` 409); `rotation_index` advances for all session squads, capped at 3 — routes_scoring.py:103-124
- §3.6 — insert — ambiguity — inquiry filing evaluates the window check before the score's terminal gate — routes_scoring.py:433-443
- §3.6 — insert — ambiguity — `NO_CHANGE` resolution records `DENIED`; the other four record `UPHELD` — routes_scoring.py:559-577
- §3.7 — insert — ambiguity — session-close precondition failures → `ERR_INVALID_STATE` (409); `all_around_rank` among `COMPLETED` entries with shared-rank/skip competition ranking — routes_core.py:301-313, logic.py:258-265
- §3.7 — insert — ambiguity — award generation: depth must be positive int (400), session must be `CLOSED` and awards not yet generated (409); all-around places use shared-place competition ranking; `was_tiebroken` pinned (tied group split by the chain; all-around always false); generation response ordered by `ceremony_order` — routes_misc.py:59-68,86-93,110-143
- §3.8 — insert — ambiguity — under `BOTH`, when the all-around path qualifies, the record pins the all-around target/score/threshold even if the event path also fired; decline error codes pinned (`ERR_COACH_CREDENTIAL_LAPSED` 422 / `ERR_UNAUTHORIZED_ROLE` 403) — logic.py:152-165, routes_misc.py:386-398
- §3.9 + §4 table — revise — mismatch — live-scores returns only the session's `PUBLISHED`/`FINAL` scores as a paginated list; dropped "current rotation, leaderboard" claims — routes_misc.py:425-433
- §4 intro — revise — mismatch — status-code rule: `assign-squads` and `auto-assign` return 200 with arrays; `generate` endpoints return 201 — routes_core.py:377, routes_people.py:347, routes_scoring.py:36,182, routes_misc.py:144

Note: the `ERR_SQUAD_CAPACITY_EXCEEDED` row was left in the §5 catalogue (harmless enumeration entry) even though no narrative now triggers it.

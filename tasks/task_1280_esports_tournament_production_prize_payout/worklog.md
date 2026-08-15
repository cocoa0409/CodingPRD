# Worklog — task_1280_esports_tournament_production_prize_payout

## Step 1: Create Task Directory — 2026-08-12T19:23:00.000Z

Task directory `tasks/task_1280_esports_tournament_production_prize_payout/` and `workspace/` pre-assigned and verified to exist (Step 1 treated as DONE per orchestrator instructions).

## Step 3: Copy Shared Files — 2026-08-12T19:24:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1280_esports_tournament_production_prize_payout/workspace/INSTRUCTION.md`.

## Step 2: Generate Scaffold — 2026-08-12T20:40:00.000Z

All checks pass. The scaffold package is complete and lint-clean. Final state:

### Files written

- `SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9)

### Verbatim lint verdict

```
Coverage
  §1.5 endpoints declared:    54
  §1.1 entities declared:     12
  §1.8 instances scanned:     19
  §1.9 instances scanned:     52
  Calls scanned (§1.8+§1.9):  1433
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

### Counts

- **Entities: 12** (Tournament, Player, Registration, RosterSlot, ServerInstance, Match, Dispute, IntegrityCase, Talent, TalentBooking, PayoutRecord, SponsorDeal)
- **State machines: 9** (incl. Match LIVE⇄PAUSED cycle + OVERTURNED fork, PayoutRecord parallel doc×disbursement dimensions, Registration/Dispute single-shot appeal cycles, Player eligibility with terminal BANNED)
- **Calculations: 10** (seed_score selector, bracket_assignment topological, placement_assignment, prize_pool_distribution waterfall w/ PROVISIONAL/FINAL variants, prize_rounding_reconciliation, withholding, talent_fee w/ quote/final variants, strike_threshold decay, roster_lock_age, server_booked_minutes)
- **Validation rules: 37** (ordered priorities 1–11, same-priority rows resolve top-first)
- **Endpoints: 54** (incl. `POST /api/_clock/set_current_utc` with mandatory default 2026-08-01T00:00:00Z)
- **Errors: 37** (all triggerable; each wired to ≥1 validation/transition and ≥1 test instance or stub)
- **Difficulty-design instances: 19** (2 per rule; combinatorial_formula has 3 covering modes (a) waterfall floor, (b) nested-rounding negative-delta tie-break, (c) royalty-band-on-base-not-total)
- **Corner-design instances: 58** (52 active recipes + 6 `excluded_because` stubs; all 9 guide sections; every error catalog entry covered)

### Design adjudications

1. **Surface vs. band**: endpoints (54) and errors (37) deliberately exceed the §0.4 Expert bands (32/30) because lint rule (f) forces a reverse-reachability GET pair per child entity (10 children) and the user explicitly requested harder-than-expert; density is concentrated in calculations/cascades/SoD gates per §0.4's difficulty guidance. Recorded as a comment in SCAFFOLD.yaml.
2. **Topology**: flat (0% in skill examples, prioritized) — one filtered list GET per child entity serves all its FKs (e.g., Match's 6 FKs via one `GET /api/matches`).
3. **Identity model**: TeamManager is `entity_backed:Registration` (X-User-ID = registration id), Player is `entity_backed:Player`; 7 opaque operator roles enable the three segregation-of-duties gates (reporter≠confirmer, doc verifier≠approver, match referee≠case resolver) via stored user-id fields.
4. **Circular-formula pin**: talent royalty band is selected from post-uplift base only (never total) — the two readings differ by exactly 9500 cents on the pinned fixture.
5. **Rounding pin**: per-record round_half_up before summation; reconciliation delta (may be negative) lands on lowest placement, ties by registration created_at ASC then seed_position ASC — never `id`.
6. **Two OCC races only** (bracket regenerate, payout compute supersede), both passing §1.2.1's serial-observability filter; all other apparent races re-classified as state preconditions.
7. **Interval semantics contrast**: server windows are half-open with a 15-minute teardown buffer (boundary-adjacent allowed); talent shifts are closed with zero buffer (touching endpoints conflict) — exercised as the two Rule-8 instances.

## Step 4: Generate PRD — 2026-08-12T20:47:00.000Z

All contracts PASS. Final report below.

---

### Summary

**File written**: `workspace/PRD.md`

#### PRD line count
**329 lines**

#### Section structure
- **§1. Introduction** — 2 paragraphs (system goals + segregated-duties frame, logical-clock callout)
- **§2. Global Specifications** — 10 subsections:
  - 2.1 User and Role-Based Access Control (9 roles with `identity:` translated; entity-backed roles called out for `TeamManager`/`Registration` and `Player`/`Player`; `SponsorManager` ownership rule)
  - 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`)
  - 2.3 Pagination (limit 10/1/100, offset 0; sort overrides for matches and payout records)
  - 2.4 Common Resource Properties and Mutation Semantics (UUID, `created_at`, `updated_at`, `version` increment contract)
  - 2.5 The Logical Clock (default `2026-08-01T00:00:00Z`, `to_iso8601`, `current_utc`)
  - 2.6 Optimistic Concurrency Control (both `concurrency_rules` with `expected_tournament_version` + `ERR_STALE_VERSION`/412)
  - 2.7 State Machines, Versioning, and Cascading Side Effects
  - 2.8 Monetary Precision and Rounding (integer cents, half-up, seed-score 3 decimals, reconciliation order)
  - 2.9 Validation Order (priority 1→11 expressed as ordered prose)
  - 2.10 Segregation of Duties (three SoD walls)
- **§3. Business Logic & Workflows** — 11 subsections organized by domain pipeline (Setup/Registration → Roster/Appeal → Lock/Bracket → Server/Schedule/Curfew → Officiate/Result/Dispute → Completion/Placement → Pool Distribution → Tax/Approve/Pay → Integrity/DQ Cascade → Talent → Sponsor)
- **§4. Endpoint Definitions** — 1 paragraph + 4-column table with all 41 endpoints
- **§5. Error Code Catalogue** — 2-column table with all 37 errors

#### Zero-Silence Rule self-audit

```
Field coverage check:
- entities[].fields: 95 required, 95 present, 0 missing
- endpoints[].request_body (input): 66 required, 66 present, 0 missing
- endpoints[].query_params: 0 declared in scaffold (all filters listed as "input" with "?" suffix), 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: priority order 1→11 expressed as ordered §2.9 prose
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint named via capability + expected_tournament_version + ERR_STALE_VERSION + 412)
- state_machines[].transitions: all 9 machines' transitions expressed (Tournament 9, Registration 10, Match 13, Dispute 5, IntegrityCase 3, TalentBooking 4, PayoutRecord 7 incl. dual-dimension, SponsorDeal 5, Player 4) with preconditions paired to error_ids and all side effects
- calculations[]: 10 checked, 10 fully expressed in precise prose (seed_score, bracket_assignment, placement_assignment, prize_pool_distribution incl. waterfall + residual sweep + reconciliation, prize_rounding_reconciliation, withholding, talent_fee PROVISIONAL/FINAL with pinned evaluation order, strike_threshold strict-greater window, roster_lock_age calendar-year rollover, server_booked_minutes 8-state inclusion set)
- validations[] conditions: 31 checked, all matchable to error_id in §2/§3 prose
- endpoints[].side_effects / applies_to: expressed in relevant workflow narrative (booked_minutes recompute on schedule/forfeit/cancel/regeneration, placement on completion advance, DQ cascade through roster slot → registration → match → server, prior-COMPUTED-voided supersede on compute, etc.)
- entities[].fields[] structured content: types/defaults/initials expressed (appeal_used false, bracket_version 0, placements_assigned false, nulls until computed, etc.)
- sibling-branch symmetry: TACTICAL vs TECHNICAL pauses, WINNER_FLIP vs REMATCH, PROVISIONAL vs FINAL (prize and talent), CLEARED vs VIOLATION, HOME vs AWAY forfeit, W9/W8BEN/GUARDIAN_W9/no-doc withholding rates — all siblings rendered with equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 636
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

#### Deliberate coverage decisions

1. **Validation-priority prose** — Rather than enumerate every priority row in §2.9, I expressed the 11 priorities as one ordered paragraph grouping categories ("auth → existence → body-shape → state → safety → constraint → temporal → fiscal → OCC"), since the scaffold's priority list is dominated by category-level ordering. Specific `applies_to` endpoint sets are rendered in §3 prose adjacent to their workflows (e.g., minor curfew and SoD live next to the schedule / confirm-result / approve discussions).

2. **Player `eligibility` SUSPEND/REINSTATE placed in §3.9** — These are `OrganizerAdmin` operations on `Player` but conceptually live beside the integrity/strike narrative where `BANNED` is discussed; grouping them together prevents a reader from missing that `BANNED` is reachable only via the strike cascade.

3. **Bye-walkover / walkover-propagation rule rendered twice** — Once in §3.3 (bracket generation) and once in §3.5 (report-result/forfeit flows), because both scaffold transition sets reference the same propagation semantics. This redundancy matches the skill's "reinforcement, not contradiction" guideline.

4. **Registration double-role of `appeal_used`** — Registration and Dispute both carry `appeal_used`; both are explicitly covered in §3.2 and §3.5 respectively with the second-appeal-rejected behavior named.

5. **`cross_region` default** — The scaffold defaults `cross_region` to false but marks it optional input; I stated "optional `cross_region` flag (default false)" to preserve both facts.

6. **Code-fence exclusion during audit** — The §2.2 verbatim block contains backtick-looking JSON; my audit correctly stripped fenced code blocks before token extraction so the verbatim JSON example did not pollute the field-coverage or path-purity counts.

## Step 5: Generate Unit Tests — 2026-08-12T21:30:00.000Z

Generation complete. Verbatim summary:

### test_helpers/ files written (9)
- `test_helpers/types.py` — 9 role/region enums, 13 status enums, 12 entity TypedDicts (all carry common fields per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (44 methods, all paths under `/api`)
- `api_errors.py` — `ApiErrorId` (37 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` plus ISO-8601 instant-comparison helpers (serialization-agnostic)
- `factories.py` — payload factories for all 12 creatable entities, input fields only
- `constants.py` — thresholds from PRD calculations (MIN_PLACEMENT_CENTS, DOC_THRESHOLD_CENTS, STRIKE_LIMIT, BUFFER_MINUTES, royalty bands, clock anchors)
- `test_users.py` — `TEST_USERS` shared headers for 7 opaque roles + fallback constants, plus `make_*_headers` builders for all 9 roles (entity-backed TeamManager/Player per PRD §2.1)
- `fixtures.py` — composite pipeline helpers: `setup_registration_open_tournament` (per-team submit/review control), `setup_locked_tournament`, `setup_seeded_tournament`, `setup_in_progress_2team`, `setup_in_progress_4team`, `setup_completed_2team`, `setup_completed_4team`, `setup_dispute_under_review`, `ban_player_with_strikes`, `issue_violation_strike`, `compute_payout_records`, `record_for_registration`, and all primitive step wrappers using `get_success_data`
- `__init__.py` — barrel export (framework generics + PRD-specific)

### test_suite/ files written (9)
- `conftest.py` + 8 test files: `test_01_envelope_and_players.py` (7), `test_02_registrations_and_rosters.py` (13), `test_03_seeding_and_bracket.py` (11), `test_04_scheduling_servers_curfew.py` (12), `test_05_match_officiating_and_disputes.py` (13), `test_06_integrity_and_strikes.py` (5), `test_07_prize_payouts.py` (19), `test_08_talent_and_sponsors.py` (10)

### Total test count
**90 tests**, collected cleanly by pytest; zero `skip`/`skipif`/`xfail` markers; every assertion value recomputed against the PRD's pinned evaluation orders (waterfall floor 125000/100000/25000/0 at pool 250000; rounding-delta 499999/500000 at pool 999999 with the residual sweep included in the derivation; talent fees 160000/214000/225625/360000; sponsor pool 900000/300000 at 1200000).

### Queue A coverage (SCAFFOLD_DIFFICULTY_DESIGN)
**19/19 instances translated, each with exactly 2 tests (38 total)** — dual_variant_calc (2 inst), combinatorial_formula (3), non_linear_state_machine (2), transitive_cascade (2), priority_pair_validation_conflict (2), boundary_precision_check (2), cross_entity_state_dependency (2), resource_temporal_overlap (2), compensating_invariant (2). None skipped.

### Queue B coverage (SCAFFOLD_CORNER_DESIGN)
**52/52 non-stub instances translated (52 tests)** — entities 6, state_machines 10, calculations 8, validations 10, endpoints 2, errors 7 (across both `errors` sections), rbac 7, cross_cutting_layers 2. None skipped. The 6 `excluded_because:` stubs (error_pause_limit_exceeded, error_talent_window_conflict, error_server_window_conflict, error_stale_version, derived_field_booked_minutes_reconciliation, compute_response_reflects_writes_immediately) were NOT translated; all six `difficulty_instance` cross-references resolve to real §1.8 instances.

### Tag-lint result
PASS — every one of the 90 tests ends its docstring with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, all resolving to real instances (19/19 difficulty, 52/52 corner); no untagged, dual-tagged, stub-pointing, or dangling tags. Separately verified: all 171 PRD citations across the suite survive whitespace-normalized verbatim grep of PRD.md; no "scaffold" references in generated code.

Notable adjudications: timestamps asserted by parsed-instant equality (never raw string equality) since PRD pins ISO-8601-with-3-fractional-digits but not `Z` vs `+00:00`; ordering-dependent tests (pagination, full seed tie) step the logical clock between creations so `created_at ASC` is load-bearing; the minor-payee approve test drops the dual-gate early-approve assertion (guardian vs tax gate ordering is not uniquely derivable from PRD §2.9) while keeping all three PRD-pinned claims.

## Step 6: Generate Implementation — 2026-08-12T21:30:00.000Z

54 routes implemented matching 54 scaffold endpoints (47 unique paths, some with both POST and GET). Everything checks out. Final summary:

---

### Implementation Summary

**Files written** (all under `workspace/implementation/`):
- `app.py` — complete single-file Flask implementation (~2000 lines), in-memory dict store keyed by id, no seeding, logical clock initialized to exactly `2026-08-01T00:00:00Z` at boot
- `start.sh` — foreground launcher with `exec`, binds `0.0.0.0:$PORT` (default 10000), guarded `pip install` (no-op when flask already importable)
- `requirements.txt` — `flask>=3.0`

**Endpoint count:** 54 routes implemented (47 unique paths), matching all 54 endpoints in the scaffold table — clock set, tournament CRUD/advance/fund/generate-bracket/compute, players create/read/eligibility, registrations create/read/list/submit/review/appeal, roster-slots create/read/list/remove, servers create/read/list/maintenance, matches read/list/schedule/officiate/report-result/confirm-result, disputes create/read/list/adjudicate/appeal, integrity-cases create/read/list/resolve, talents create, talent-bookings create/read/list/transition, payout-records read/list/submit-docs/verify-docs/approve/pay, sponsor-deals create/read/list/transition.

**State machines implemented (9):** Tournament (DRAFT→REGISTRATION_OPEN→REGISTRATION_LOCKED→SEEDED cyclic-regen→IN_PROGRESS→COMPLETED→PAYOUTS_FINALIZED, plus 3 cancel paths with cascades), Registration (DRAFT→SUBMITTED→APPROVED/REJECTED↔APPEALED once→LOCKED→FORFEITED), RosterSlot (ACTIVE→REMOVED/INELIGIBLE), Match (PENDING→SCHEDULED→LOBBY_OPEN→LIVE↔PAUSED→COMPLETED→CONFIRMED/UNDER_DISPUTE→OVERTURNED→{CONFIRMED|SCHEDULED}, FORFEIT from 5 states with walkover propagation, CANCELLED), Dispute (FILED→UNDER_REVIEW→CLOSED_UPHELD/CLOSED_OVERTURNED, appeal cycle), IntegrityCase (OPEN→INVESTIGATING→RESOLVED_CLEARED/RESOLVED_VIOLATION with strike append + DQ cascade), TalentBooking (TENTATIVE→CONFIRMED→SETTLED/CANCELLED), PayoutRecord (parallel dimensions: disbursement COMPUTED→APPROVED→PAID/VOID; doc PENDING→SUBMITTED→VERIFIED/REJECTED→SUBMITTED resubmit), SponsorDeal (PROPOSED→CONTRACTED→ACTIVATED, VOID from all non-terminal), Player eligibility (ELIGIBLE↔SUSPENDED, →BANNED terminal via strikes).

**Calculations implemented (9):** seed_score (0.5/0.3/0.2×10 weights, 3-decimal ROUND_HALF_UP, selector score DESC → qualifier_wins DESC → created_at ASC → team_name ASC), bracket_assignment (power-of-2 sizing, seed i vs size+1−i pairing, bye walkovers created directly in FORFEIT with immediate propagation, next_match_id = ceil(k/2)), placement_assignment (champion=1, loser at round r = 2^(R−r)+1, FORFEITED regs keep null), prize_pool_distribution (6-step pinned order: sponsor-bonus pool, eligible set, base pcts 50/25/12.5, FINAL pro-rata redistribution of forfeited shares, waterfall with 100000 floor, residual sweep to placement-1, per-record round-half-up then delta reconciliation — all Decimal-based), prize_rounding_reconciliation, withholding (W9/GUARDIAN_W9 0%, W8BEN 30%, no-verified-doc 24% backup, 60000 inclusive threshold), talent_fee (PROVISIONAL = ceil(h/8)×rate; FINAL = pinned order with 1.15 cross-region uplift on base only, overtime at 1.5× hourly over 8h, royalty band from post-uplift base only 0/5/10%), strike_threshold (strictly-after now−365d window, ban at ≥3), roster_lock_age (calendar-year rollover, 18th birthday on lock day = not minor), server_booked_minutes (duration+15 buffer over the 8 booked statuses).

**Validations implemented:** full priority-ordered pipeline per PRD §2.9 — auth (401 ERR_UNAUTHENTICATED missing/unrecognized `X-User-ID`/`X-User-Role`, 403 ERR_FORBIDDEN role matrix, 403 ERR_OWNERSHIP_MISMATCH for TeamManager=Registration.id / Player=payee_player_id / SponsorManager=contact_user_id) → existence 404 left-to-right → body shape 400 → state 409 (8 entity-specific error ids) → business-safety 422 (minor curfew strict-before, guardian docs, tax threshold, three SoD walls) → business-constraint (handle/team/slot uniqueness, double-roster, roster shape, eligibility+captain, half-open server window with 15-min buffer and adjacency allowed, closed-interval talent window where back-to-back conflicts, region mismatch, tactical pause limit 2, match participant, appeal budget, bracket-locked-downstream, server maintenance) → temporal (registration window inclusive both ends, dispute window, schedule-in-past) → fiscal (insufficient field, underfunded pool with equality allowed, integrity cases pending, payout-not-final) → OCC 412 ERR_STALE_VERSION last on generate-bracket and payout compute.

**Smoke boot:** `bash start.sh` boots cleanly from a fresh process in ~0.7s (well under the 60s limit), store verified empty at boot, clock reads the exact default, and three smoke suites (base lifecycle + extended corner cases + targeted calculation checks covering bye walkovers, regeneration cancel, curfew pass/violation, DQ cascade with server-minute release, WINNER_FLIP and REMATCH remedies, 4-team placements 1/2/3/3, sponsor bonus pool, W8BEN 30% withholding, minor guardian docs, doc resubmission, strike 365-day decay boundary, pagination meta) all pass end-to-end.

Two fidelity decisions worth noting: (1) on approve, `ERR_PAYOUT_NOT_FINAL` is evaluated before the doc gates, following PRD §3.8's prose order ("The record's `compute_run_mode` must be `FINAL` … The tax threshold applies …") over the scaffold's numeric priority; (2) placement assignment skips FORFEITED registrations entirely per PRD §3.6 ("keep placement null"), which also drives their exclusion from both compute modes.

## Step 7: Run Tests and Iterate — 2026-08-12T21:55:00.000Z

All 8 rounds pass: 90/90 in every round. Clean sweep achieved.

### Summary

**Iterations run:** 2 (first sweep surfaced 6 deterministic + 5 flaky failures; second sweep after fixes: 8/8 rounds fully green, 720/720 test executions passed).

**Tests deleted:** none. Every failing test traced to a verbatim PRD rule with unique derivability; no PRD-silence or collapse-pattern deletions were needed.

**Fixes applied to `test_suite/`** (`test_suite/test_02_registrations_and_rosters.py`):
- `test_registration_appeal_cycle_completes_once`, `test_registration_second_appeal_rejected`, `test_double_submit_returns_invalid_registration_status`, `test_team_manager_cannot_review_own_registration` — the tests require a `SUBMITTED` registration as precondition (they assert it, and PRD §3.2 restricts review to `SUBMITTED`/`APPEALED`), but called `setup_registration_open_tournament` with default specs whose `review="APPROVE"` default left registrations `APPROVED`. Each call now passes an explicit `team_specs` entry with `"review": None`, matching the convention already used elsewhere in the same file. The fixture itself was correct (83 other tests rely on its approve-by-default pipeline); only these four call sites were wrong.
- `test_double_roster_add_returns_player_double_rostered` — the assertion `data == []` on r2's slot listing was wrong: r2 legitimately holds p2's own slot from setup. Narrowed to assert only that no slot for p1 exists on r2, which is what the PRD §3.2 double-roster rejection actually implies (same shape as the neighboring ownership test's `len(data) == 1`).

**Fixes applied to `implementation/`** (`workspace/implementation/`):
- `app.py`, `transition_sponsor_deal` — moved the ACTIVATE ownership check (`contact_user_id == X-User-ID` → `ERR_OWNERSHIP_MISMATCH`) ahead of the `CONTRACTED` from-state check. PRD §2.9 fixes the validation order: "Auth checks come first (missing headers, then role, then ownership)... Then come per-entity state-machine from-state checks." The implementation was checking state before ownership, so an ACTIVATE on a `PROPOSED` deal by the wrong `SponsorManager` returned `ERR_INVALID_DEAL_STATUS` instead of `ERR_OWNERSHIP_MISMATCH`.
- `app.py` boot + `requirements.txt` — the flaky per-round failures in `test_05` (mid-test `RemoteDisconnected`/`IncompleteRead`, and intermittent "could not be restarted" setup failures under the 8-round concurrent load) were transport-layer: the Werkzeug dev server drops/resets connections when CPU-starved during ~8× parallel per-test restarts. Switched the server transport to waitress (`threads=8, backlog=1024, connection_limit=1000, channel_timeout=60`) with Werkzeug fallback, and pinned `waitress==3.0.2` in requirements. No behavior change — only the WSGI transport. This is the established hardening pattern from prior tasks in the repo (e.g. tasks-batch-2).

## Step 8: Finalize PRD — 2026-08-12T22:05:00.000Z

Done. `PRD_FINALIZED.md` exists at `workspace/PRD_FINALIZED.md` as a byte-identical copy of `PRD.md`. The minimal correct patch is the **empty patch**: every `<step_7_diff>` item traces to behavior the PRD already uniquely determines, or to a non-behavioral change.

### Line counts and delta

- `PRD.md`: 329 lines; `PRD_FINALIZED.md`: 329 lines; delta **0%** (0 insertions, 0 deletions).

### Per-change bullets (all resolved as "no edit — PRD already pins / no behavioral delta")

- **§3.2 (registration review/appeal/submit)** — *no change* — the four test fixes (`"review": None` call sites in `test_02_registrations_and_rosters.py`) were pure fixture call-site bugs; PRD §3.2 already pins "Review is performed by a `TournamentDirector` against a `SUBMITTED` or `APPEALED` registration", the appeal-once cycle, and submit-from-`DRAFT` only (with §2.7's invalid-status rule and §4's review RBAC). Evidence: `test_suite/test_02_registrations_and_rosters.py:30-308`, `test_helpers/fixtures.py:484-509`.
- **§3.2 (double-roster)** — *no change* — the narrowed assertion (`no slot for p1 on r2` instead of `data == []`) was an over-strong test assertion; PRD §3.2 already pins `ERR_PLAYER_DOUBLE_ROSTERED` and the roster model that legitimately leaves p2's own slot on r2. Evidence: `test_suite/test_02_registrations_and_rosters.py:257-283`.
- **§2.9 / §3.11 (sponsor ACTIVATE ordering)** — *no change* — the `implementation/` fix moved the ownership check ahead of the from-state check to match what PRD §2.9 already pins verbatim ("Auth checks come first (missing headers, then role, then ownership)... Then come per-entity state-machine from-state checks"). The impl was wrong, not the PRD; no residual mismatch. Evidence: `implementation/app.py:2426-2434`.
- **(transport) waitress switch** — *no change* — WSGI transport hardening (`app.py:2451-2465`, `requirements.txt`) with explicitly zero behavior change; the PRD is an API-behavior spec and INSTRUCTION.md pins only PORT/0.0.0.0/foreground, so server choice is a free implementation detail outside PRD scope.

### Per-edit pre-edit search log (each candidate edit, searched and rejected)

1. **Candidate: pin ownership-before-state order for sponsor ACTIVATE.**
   (a) Subject: validation order in `transition_sponsor_deal`.
   (b) Enumerated and read: `implementation/app.py:2412-2442` (full `transition_sponsor_deal`); all 8 `err_ownership` call sites via grep (`app.py:1334, 1413, 1447, 1491, 1831, 1955, 2253, 2430`); spot-read `submit_registration` (`app.py:1328-1370`) and `submit_docs` (`app.py:2243-2269`) — every site already checks ownership before from-state, matching PRD §2.9 verbatim. Also read the asserting tests `test_08_talent_and_sponsors.py:250-312` (wrong-owner-on-PROPOSED → `ERR_OWNERSHIP_MISMATCH`; right-owner-on-PROPOSED → `ERR_INVALID_DEAL_STATUS`), both derivable from §2.9 + §3.11.
   (c) No wording committed: PRD §2.9 already uniquely determines the fixed behavior; adding a sentence would duplicate an existing universal rule without new information.

2. **Candidate: pin that review requires `SUBMITTED`/`APPEALED` precondition.**
   (a) Subject: registration review eligibility.
   (b) Enumerated and read: review endpoint tests `test_02_registrations_and_rosters.py:30-308`; fixture pipeline `test_helpers/fixtures.py:482-509`; PRD §3.2 line 130 and §4 review row.
   (c) No wording committed: PRD §3.2 already states review is "against a `SUBMITTED` or `APPEALED` registration"; the failures were fixture defaults approving registrations, i.e. test-only bugs.

3. **Candidate: pin roster-slot listing contents after a rejected double-roster add.**
   (a) Subject: roster uniqueness and list semantics.
   (b) Enumerated and read: `test_02_registrations_and_rosters.py:257-283`; PRD §3.2 lines 126-128 (uniqueness floor, `ERR_PLAYER_DOUBLE_ROSTERED`).
   (c) No wording committed: the PRD pins the rejection; the surviving-slot content follows from the roster model. The original `data == []` assertion was a test bug, not a PRD silence.

4. **Candidate: pin WSGI transport (waitress).**
   (a) Subject: server transport.
   (b) Enumerated and read: `app.py:2445-2465` (boot), `requirements.txt`, `INSTRUCTION.md` (contract: PORT/0.0.0.0/foreground only).
   (c) No wording committed: transport has no API-behavioral consequence and INSTRUCTION.md leaves it free; the step_7_diff itself states "No behavior change — only the WSGI transport."

Step 7's own summary corroborates this outcome: "Every failing test traced to a verbatim PRD rule with unique derivability; no PRD-silence or collapse-pattern deletions were needed." A fresh implementer reading `PRD_FINALIZED.md` (≡ `PRD.md`) already has every rule needed to reproduce the current `implementation/` behavior at all Step 7 sites.

## Step 9: Complete PRD — 2026-08-12T22:20:00.000Z

All edits applied cleanly — 29 single-paragraph hunks, line count unchanged, +5605 chars.

### Summary

**Source**: `PRD_FINALIZED.md` (329 lines, 51878 chars) → `PRD_COMPLETED.md` (329 lines, 57483 chars), char-delta **+5605**. Line count unchanged — all changes are inline paragraph inserts/revisions; no new sections.

**Counts**: 25 ambiguity-pins, 4 mismatch-revisions (29 paragraphs touched; two paragraphs carry both a pin and a revision).

#### Changes

- §2.3 — insert — ambiguity — invalid `limit`/`offset` (non-integer, out of [1,100], negative offset) rejected with `ERR_VALIDATION` 400 — app.py:307-328
- §2.3 — insert — ambiguity — list sorts break `created_at` ties on `id` ascending; payout list adds record-`id` final tiebreak — app.py:1324, 2231-2234
- §2.7 — insert — ambiguity — server-maintenance and player-eligibility actions naming the current/invalid from-state deviate to `ERR_VALIDATION` 400 instead of a 409 invalid-status error — app.py:1584-1594, 1251-1258
- §2.9 — revise — mismatch — pinned two exceptions to the generic priority order: schedule's server-`ACTIVE` check runs before the curfew safety check, and payout approval's `FINAL`-mode gate runs before the safety gates — app.py:1653-1672, 2301-2316
- §3.1 — insert — ambiguity — tournament-creation shape rules (target ≥ 0, roster sizes ≥ 1, max ≥ roster, curfew `HH:MM` 00:00–23:59) all rejected with `ERR_VALIDATION` — app.py:821-830
- §3.1 — insert — ambiguity — funding allowed only in `DRAFT`/`REGISTRATION_OPEN`/`REGISTRATION_LOCKED`/`SEEDED` (else `ERR_INVALID_TOURNAMENT_STATUS` 409); `amount_cents` must be ≥ 1 — app.py:863-865
- §3.2 — insert — ambiguity — registration create validates `tournament_id`/`captain_player_id` existence (`ERR_NOT_FOUND`); duplicate `team_name` in a tournament → `ERR_HANDLE_TAKEN` 409 — app.py:1273-1284
- §3.2 — insert — ambiguity — roster-slot add requires registration `DRAFT` and rejects adds exceeding `max_roster_size` with `ERR_ROSTER_SIZE_VIOLATION` — app.py:1448-1471
- §3.2 — insert — ambiguity — slot removal requires registration `DRAFT` and slot `ACTIVE`, else `ERR_INVALID_REGISTRATION_STATUS` — app.py:1492-1497
- §3.3 — insert — ambiguity — lock-advance clock gate failure → `ERR_INVALID_TOURNAMENT_STATUS` 409 — app.py:897-900
- §3.3 — insert — ambiguity — regeneration "matches underway" gate failure → `ERR_INVALID_TOURNAMENT_STATUS` 409 — app.py:1003-1006
- §3.3 — insert — ambiguity — walkover matches set `completed_at` and `dispute_window_closes_at` to the logical clock at generation — app.py:664-665
- §3.3 — insert — ambiguity — seeding increments each `LOCKED` registration's `version`; generate-bracket returns HTTP 201 with the updated tournament in `data` — app.py:1045-1054
- §3.3 — insert — ambiguity — `SEEDED → IN_PROGRESS` round-1 scheduling gate failure → `ERR_INVALID_TOURNAMENT_STATUS` 409 — app.py:926-929
- §3.4 — insert — ambiguity — maintenance-enter block uses `ERR_SERVER_IN_MAINTENANCE` 422; no-op `ENTER`/`EXIT` → `ERR_VALIDATION` 400 — app.py:1583-1594
- §3.4 — revise — mismatch — `assigned_referee_id` is taken from the request body (not "the assigned referee's `X-User-ID`"); body fields pinned (`server_id`, `scheduled_start_at`, `duration_minutes` ≥ 1, `assigned_referee_id`); cross-tournament server → `ERR_VALIDATION` — app.py:1634-1654
- §3.4 — insert — ambiguity — scheduling check firing order: server-`ACTIVE` → curfew → window-overlap → schedule-in-past — app.py:1653-1694
- §3.5 — insert — ambiguity — `OPEN_LOBBY` error ids: non-`LOCKED` participant → `ERR_INVALID_MATCH_STATUS`; non-`ACTIVE` server → `ERR_SERVER_IN_MAINTENANCE` — app.py:1715-1726
- §3.5 — insert — ambiguity — `RULE_UPHELD` performs no match cascade and does not rewrite `confirmed_by_user_id` when the match is already `CONFIRMED` (re-review after appeal) — app.py:1895-1898
- §3.5 — insert — ambiguity — `RULE_OVERTURNED` match cascades apply only while the match is `UNDER_DISPUTE` — app.py:1922
- §3.5 — insert — ambiguity — `WINNER_FLIP` records the adjudicating director as the match's `confirmed_by_user_id` — app.py:1931-1932
- §3.6 — insert — ambiguity — `IN_PROGRESS → COMPLETED` and `COMPLETED → PAYOUTS_FINALIZED` gate failures → `ERR_INVALID_TOURNAMENT_STATUS` 409 — app.py:931-947
- §3.7 — insert — ambiguity — payout compute requires tournament `COMPLETED`, else `ERR_INVALID_TOURNAMENT_STATUS` 409 — app.py:1074-1076
- §3.7 — insert — ambiguity — residual-sweep tiebreak gets final `seed_position` ascending fallback (impl `waterfall_key`) — app.py:1132-1133, 1154-1155
- §3.7 — insert — ambiguity — record field pins: `payee_player_id` = registration's `captain_player_id`, `placement` copied, doc/guardian/verifier/approver/`paid_at` start null; compute returns HTTP 201 with the new-record array in waterfall order — app.py:1173-1206
- §3.8 — insert — ambiguity — doc submission accepted only from `doc_status` `PENDING`/`REJECTED` (else `ERR_INVALID_PAYOUT_STATUS`); guardian fields stored only for minor payees — app.py:2261-2267
- §3.8 — revise — mismatch — approve gate order pinned as FINAL-mode → minor gate → tax threshold → SoD (PRD prose previously ordered tax before minor; impl checks minor first) — app.py:2306-2319
- §3.9 — insert — ambiguity — new player starts `ELIGIBLE` with empty `ac_strike_events` — app.py:1226-1232
- §3.9 — insert — mismatch — eligibility `SUSPEND`/`REINSTATE` from a non-permitting state → `ERR_VALIDATION` 400 (not a 409 invalid-status error as §2.7's generic rule would imply) — app.py:1251-1258
- §3.9 — insert — ambiguity — DQ-cascade "non-terminal match" enumerated (`PENDING`…`OVERTURNED`, excluding `CONFIRMED`); system forfeit sets winner, `forfeiting_registration_id`, `completed_at`, `dispute_window_closes_at` — app.py:676, 680-699
- §3.10 — insert — ambiguity — `shift_end_at` not strictly after start → `ERR_VALIDATION` — app.py:2124-2125
- §3.10 — insert — ambiguity — booking `CONFIRM`/`SETTLE` tournament-state gate failures → `ERR_INVALID_BOOKING_STATUS` 409 — app.py:2182-2196
- §3.11 — insert — ambiguity — per-action role restriction: `CONTRACT`/`VOID` reject `SponsorManager` with `ERR_FORBIDDEN`; `ACTIVATE` rejects any non-`SponsorManager` (incl. `OrganizerAdmin`) with `ERR_FORBIDDEN` — app.py:2420-2439

**Notable judgment calls**: the two genuine prose-vs-code ordering conflicts (§2.9 generic priority vs. impl's schedule/approve check order; §3.8 approve-gate order) were resolved in favor of impl, with §2.9 amended to name the two local exceptions rather than rewritten.

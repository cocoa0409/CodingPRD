# Worklog — task_2289_festival_talent_buying_radius_administration

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2289_festival_talent_buying_radius_administration/` and `workspace/` subdirectory (pre-allocated name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T00:00:00.000Z

Scaffold for task 2289 is complete and lints clean.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2289_festival_talent_buying_radius_administration/`):
- `SCAFFOLD.yaml` (3531 lines, §1.0–§1.7 only, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## Scaffold contents
- **Envelope**: `domain_name: festival-talent-buying`, `api_prefix: /festival-ops`, consistency `immediate`, role model `segregation_of_duties`, topology flat, state-machine shape cyclic; complexity layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation, rate_threshold_triggers.
- **12 entities**: Festival, BudgetTier, Stage, Artist, Offer, RadiusClause, CompetingPerformance, Booking, RiderItem, AdvancePacket, PaymentInstallment, AnnouncementWave.
- **10 state machines** (incl. Booking as two parallel dimensions `contract_status` × `settlement_status`, cyclic Offer negotiation bounded at 3 rounds, cyclic AdvancePacket submit/return, LOCKED→PLANNED wave fallback, Festival announcement_phase) + **3 concurrency rules** (Festival/Booking/Wave OCC).
- **14 calculations**, incl. tier waterfall, `genre_balance_share`, `offer_guarantee_ceiling` (nested min over 3 inputs), `rider_cost_estimate` (PROPOSED_SCOPE/CONTRACTED_SCOPE), `artist_radius_risk_score` (STRICT/ADJUDICATED), `radius_conflict_detection` (haversine), `payment_schedule_build`, `settlement_total`, `deposit_recovery` (CONTRACTUAL/ACTUAL), `festival_lineup_posture`.
- **51 ordered validations** (priorities 1–76), **60 endpoints**, **69-entry error catalog**, **5 RBAC roles** (TalentBuyer, ArtistRep [entity_backed:Artist], BusinessAffairs, ProductionManager, FinanceController) with SoD on advance approval (priority 42) and ArtistRep identity binding (priority 13). Four cascades: accept commitment (depth 5), cancel compensation (depth 4), breach enforcement (depth 4), waiver grant.

## Design files
- **§1.8 difficulty design: 27 instances** = all 9 rule_ids × 3 (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- **§1.9 corner design: 115 instances across all 9 sections — 76 with full test recipes, 39 `excluded_because` stubs**: entities 11, state_machines 19, calculations 24, validations 34, endpoints 11, errors 4, rbac 5, cross-cutting complexity layers 6, consistency model 1.

Verification beyond the linter: 140 instance names unique across both design files; zero unbound `${...}` placeholders (every reference bound by an earlier capture in the same recipe); all 39 stubs cite existing §1.8 instances; every `ERR_*` mentioned exists in the catalog and all 69 catalog ids are exercised; all 60 §1.5 endpoints appear as real calls. Fixtures were pre-checked against the ordered validation table so each negative probe's intended rule is the first one violated (e.g. OCC priority 15 beating ERR_ALLOCATION_LOCKED/71 and ERR_BOOKING_ALREADY_ASSIGNED/64; ERR_WAVE_PHASE_MISMATCH/36 beating ERR_EMPTY_WAVE/63; role 3 before existence 10 before scope 13).

One SCAFFOLD.yaml consistency repair was applied during generation: the Offer DRAFT→ISSUED precondition on billing position 1 was broadened to match validation priority 62 (flagship stage required for any tier, not just HEADLINER).

## Step 3: Copy shared files — 2026-09-01T00:00:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T00:00:00.000Z

PRD generation complete.

**Output:** `workspace/PRD.md` — 502 lines.

**Structure** (25 headings; ends at §5 with no audit footer):
- §1 Introduction (3 paragraphs)
- §2 Global Specifications, 11 subsections: 2.1 Actors/Identity Headers/Role Permissions, 2.2 API Response Structure (byte-for-byte verbatim from `section-2.2-response-structure.md`, verified), 2.3 Pagination & List Ordering, 2.4 Common Resource Properties, 2.5 The Logical Clock, 2.6 Optimistic Concurrency on Parent Records, 2.7 Cents/Minutes/Rounding Discipline, 2.8 Validation Precedence (all 51 ranks as an ordered ladder + the 3 conflict-pair consequences + the concrete 12-step issuance order), 2.9 Conservation of Budget and Stage Time, 2.10 Cascades & Derived-Field Reconciliation, 2.11 Nested Reads & Path Resolution
- §3 Business Logic & Workflows, 9 subsections (edition/waterfall; stage estate/curfew/day load; roster/genre balance/guarantee ceiling; offer negotiation; acceptance cascade/payment schedule; radius enforcement/waiver; riders/advance/countersignature; money movement/settlement; announcements/cancellation/recovery)
- §4 Endpoint Definitions — 60 rows, exactly 4 columns
- §5 Error Code Catalogue — 69 rows, exactly 2 columns

**Hard Contract audits (two passes on Contract 1):**

```
Field coverage check:
- entities[].fields: 131 required, 131 present, 0 missing
- endpoints[].request_body: 85 required, 85 present, 0 missing
- endpoints[].query_params: 24 required, 24 present, 0 missing
- computed response shapes: 33 required, 33 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validation priority ordering: 51 of 51 ranks rendered in one strict ladder — PASS
- concurrency_rules[] OCC rejections: 3 of 3 (expected_festival_version/ERR_STALE_FESTIVAL_VERSION, expected_booking_version/ERR_STALE_BOOKING_VERSION, expected_announcement_wave_version/ERR_STALE_WAVE_VERSION, all 412), framed as stale-version only — PASS
- cross-entity side effects / cascades: 4 of 4 four-hop cascades, every hop attributed — PASS
- validations[].applies_to endpoint sets: 51 of 51 exact (incl. event-window enforced at draft+revise but not issuance) — PASS
- field-level structured content: 131 fields with ranges/enums; 52 of 52 declared defaults & initial values stated — PASS
- sibling-branch symmetry: adjudicate CLEARED/VIOLATION, waiver GRANTED/DENIED, rider APPROVED/REJECTED/SUBSTITUTED all given equal weight — PASS
- state transitions: every declared transition's from/to present with preconditions paired to error_id and side effects (10 machines incl. Booking's two parallel dimensions) — PASS
- calculations: 14 of 14 formulas in prose, all 22 named constants' values present — PASS
- endpoints[].side_effects: 60 of 60 endpoints' effects narrated — PASS
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1033
- tokens starting with /: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Notable scaffold reconciliations** (resolved in favour of the authoritative source, no invention): the scaffold spells the header `X-User-Id` while the skill mandates `X-User-ID` — the skill's spelling is used throughout; `headliner_anchor_count` has an aggregate definition on the entity and a `billing_position == 1` increment note on the accept endpoint — the aggregate definition wins, per §2.10's stated rule; `RELEASED → VOIDED` is listed on the installment machine for guarantee amendment while the same entry and the amendment endpoint both say released rows are never rewritten — documented as amendment voiding/rebuilding only `SCHEDULED` rows, with cancellation voiding `SCHEDULED`, `HELD` and `RELEASED`.

The two withheld design files were not opened, grepped, or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-01T00:00:00.000Z

Stage 1 and Stage 2 are complete and audited.

## Files written

**`test_helpers/`** (9 modules, written by me):
`__init__.py` (registers the error→status map on import), `constants.py` (roles, enums, all named numeric rules, canonical Harbor Lights literals), `api_errors.py` (all 69 error ids + `set_error_http_status_map`), `test_users.py` (opaque operator identities + `make_artist_rep_headers(artist_id)`), `api_client.py` (one method per endpoint, 60 endpoints), `factories.py` (payload builders; passing a field as `None` omits it), `assertions.py` (round-half-up, haversine/distance, line cost, both risk variants, deposit band, promoter share, settlement total as pure functions + envelope/common-field assertions), `types.py` (12 TypedDicts, all carrying `id`/`created_at`/`updated_at`/`version`), `fixtures.py` (composite builders: single-tier and three-tier editions, draft/issued offers, accepted / rider-settled / countersigned bookings, breached-clause booking, installment pay, locked wave).

**`test_suite/`**: `conftest.py` + 18 test files, **166 tests**, all collecting cleanly (`pytest test_suite --collect-only` → 166 collected, no errors).

## Test counts per queue
- **Queue A (Difficulty)** — 90 tests across `test_01`–`test_09`. All 27 instances covered, every one with ≥2 tests (cascade instances carry up to 6).
- **Queue B (Corner)** — 76 tests across `test_10`–`test_18`. 74 of 76 non-stub instances covered (≥1 each); all 39 `excluded_because:` stubs untranslated, and every stub's `difficulty_instance:` cross-reference resolves to a real difficulty instance (zero dangling).

## Instances skipped (PRD-first filter)
Only two, both in the corner `validations` section:
1. `offer_issue_before_the_waterfall_is_rejected_at_priority_34` — before allocation each tier's `allocation_cents` is 0, so every tier derives as `CLOSED`, which forces `lineup_posture` to `FROZEN`; `ERR_LINEUP_FROZEN` therefore outranks the asserted `ERR_TIERS_NOT_ALLOCATED` and the asserted outcome is unreachable.
2. `granted_waiver_on_an_unadjudicated_report_rejected` — with the report still `REPORTED` the clause is `ACTIVE`, so `ERR_INVALID_CLAUSE_STATE` fires before the asserted `ERR_ADJUDICATION_MISMATCH`.

Assertion-level skips (instance still covered) were also taken where the PRD does not uniquely derive a figure: `guarantee_ceiling_cents` / `genre_balance_factor` on a never-issued DRAFT offer; `zeroed_line_count` and `capped_line_count` definitions on the rider-estimate read; `created_at == updated_at` at creation; `strict_risk_score` after a NO_CONFLICT report; a negative-`offset` pagination probe (400 vs 422 ambiguous).

## Design-index defects worth reporting upstream
- One difficulty instance asserts `round_number == 0` right after issuance while the PRD (and its sibling instance) require 1.
- `accept_offer_depth5_commitment_cascade` states a balance `due_date` of 2026-12-05 for a slot starting 2026-12-04; the PRD derives 2026-12-04.
- Two `compensating_invariant` instances and `offer_issuance_blocked_by_frozen_parent_festival` contain replay steps the PRD blocks earlier (`ERR_BILLING_POSITION_TAKEN` on a replacement reusing ordinal 1 while the original offer stays `ACCEPTED`; `ERR_OFFER_NOT_NEGOTIABLE` from supersession before the frozen-posture check).
- A few recipe payloads use genres outside the PRD enum (`FOLK`, `JAZZ`) and a `tier_rank: 9` outside 1–4; substituted with in-range values that leave the asserted figures unchanged.

## Coverage audit result
Automated audit over all 18 files: **0 problems** — every test has exactly one `Design:` line as the final docstring line, every tag resolves to a real instance (no stub is tagged), every docstring contains a quote that matches `workspace/PRD.md` verbatim after whitespace normalisation, and no generated file mentions the design documents. Queue A: 0 instances with fewer than 2 tests. Queue B: 74/76 non-stub instances tested, 2 principled skips as above.

## Step 6: Generate implementation — 2026-09-01T00:00:00.000Z

Implementation is complete and verified.

## Files written

`workspace/implementation/`

```
start.sh                    # exec python3 app.py, 0.0.0.0, $PORT (default 10000), guarded pip install
requirements.txt
app.py                      # create_app(); 9 blueprints @ /festival-ops; ApiError/HTTPException/catch-all handlers
db.py                       # Store (12 in-memory dicts), logical clock, new_row/touch/apply_changes/public
errors.py                   # 69-entry ERROR_STATUS catalogue, ApiError, fail()
response.py                 # envelope (meta/response_type/data), req_<20 ALNUM> ids, paginate()
middleware.py               # 5 roles, auth ranks 1-3, ArtistRep row-level scoping
validators.py               # typed body/query coercion, FK loader, version checks
services/calc.py            # 14 pinned calculations + all domain constants
services/derive.py          # aggregate re-derivations + the 4 four-hop cascades
routes/festivals.py (11) artists.py (4) offers.py (9) radius_clauses.py (4)
      competing_performances.py (4) bookings.py (11) advance_packets.py (6)
      payment_installments.py (5) announcement_waves.py (6)
```

## Endpoint count

**60 routes registered = 60 SCAFFOLD endpoints**, exact set match after normalizing path-parameter names (`MISSING: []`, `EXTRA: []`). The raw diff only shows `<id>` vs `<booking_id>` naming, which does not affect Flask routing.

## Self-verification performed

- **Fresh boot**: server starts from a cold process in ~5s and answers `GET /festival-ops/festivals`. `start.sh` skips pip when Flask is importable, so the per-test-server reboot loop does not contend on installs.
- **Empty store guarantee**: all 12 collections report length 0 at import time; logical clock defaults to `2026-08-01T00:00:00+00:00`. Nothing is ever seeded.
- **Error catalogue**: programmatically diffed against PRD §5 — 0 missing, 0 extra, 0 HTTP-status mismatches across all 69 ids.
- **Smoke suite A** (62 assertions) and **smoke suite B** (26 assertions) both run end-to-end against one fresh boot with **0 failures**. Coverage includes: festival create/allocate-tiers/advance-phase, offer draft→issue→counter→revise→accept, the commitment cascade, rider items + settlement waterfall, advance packet submit/return/approve with segregation of duties and the stage-day channel cap, countersign, installment release/mark-paid, guarantee amendment, wave plan/assign/lock/publish, cancel + clawback + RECOVERED, expired-offer sweep, radius breach adjudication and waiver, plus envelope/RBAC/pagination/404/422 negative cases.

## Key finding fixed during verification

`services/derive.py::rebuild_schedule` broke the installment-total conservation law when a guarantee amendment landed on a booking with **no SCHEDULED rows left** (deposit PAID, balance RELEASED): the non-voided sum stayed at the old guarantee. Added a fallback that synthesizes a single `BALANCE` row for the delta when `rebuild_types` is empty and `remaining != 0`.

Constraint compliance: only `INSTRUCTION.md`, `SCAFFOLD.yaml`, `PRD.md`, the generator SKILL, and my own generated files were read. No access to `test_suite/`, `test_helpers/`, the difficulty/corner design YAMLs, or any sibling task directory.

## Step 7: Run tests and iterate — 2026-09-01T00:00:00.000Z

All background runs stopped, temporary probe directory and results files removed, task directory left with only the intended edits.

## Summary

### Iterations run
Five full 8-round parallel sweeps (each round = all 166 tests, `--isolation per-test-server`), plus 8 supplementary rounds over a `test_12`–`test_18` subset to reach the tail of the suite that saturated rounds rarely got to. Six fix batches, each followed by a fresh sweep.

### Tests deleted
**None.** No failing assertion in this task traced to PRD silence or to a non-uniquely-derivable rule, so STEP 1a/1b never fired. Every genuine failure resolved at STEP 2 (one test was wrong) or STEP 3 (five implementation defects).

### Fixes applied to `test_helpers/`
**None.** (Noted but deliberately untouched: `test_helpers/constants.py` lists `"INDIE_ROCK"` in `GENRES` where PRD §3.3 says `ROCK`; `GENRES`/`GENRE_FOCUS_VALUES` are referenced by no test, so changing it would be churn.)

### Fixes applied to `test_suite/`
- `test_suite/test_12_calculation_details.py` — `test_draw_penalty_rounds_half_up_and_both_variants_agree_without_reports`: the two assertions on the *stored* artist row changed from `== 12` to `== 0`. PRD §3.2 line 239 verbatim: "A new act starts with `reported_conflict_count`, `radius_breach_count`, `strict_risk_score` and `adjudicated_risk_score` all at 0." The same file's `test_conflict_detection_ignores_a_provisional_clause` asserts `strict_risk_score == 0` on a new act, so the two tests contradicted each other; PRD uniquely determines 0. The test's assertions on the *computed* read (`get_radius_risk` → 12) were left exactly as written.

### Fixes applied to `implementation/`
- `workspace/implementation/routes/announcement_waves.py` → `assign_booking`: now returns the **wave**, not the booking. PRD §4: "returns the resource it acted on … Path parameters are always the `id` of the named resource." Fixed 3 hard `ERR_ANNOUNCEMENT_WAVE_NOT_FOUND` failures reproducing in 8/8 rounds.
- `workspace/implementation/services/derive.py` → `cascade_cancel`: hop four now clears `booking["announcement_wave_id"]` (before the single `touch`, so cancel stays one version bump). PRD §3.10: "Hop four removes the booking from its announcement wave…".
- `workspace/implementation/services/calc.py` → `rider_totals`: a capped `HOSPITALITY` line now counts toward `priced_line_count` as well as `capped_line_count` (previously mutually exclusive). Single reading that satisfies all five assertion sites.
- `workspace/implementation/routes/bookings.py` → `list_rider_items`: sort key `("category", asc)`. PRD §2.3: rider items by `category` ascending.
- `workspace/implementation/routes/payment_installments.py` → `list_booking_installments`: sort key changed from `sequence_index` to `("due_date", asc)`. PRD §2.3: payment installments by `due_date` ascending.

Storage remains in-memory only (`db.py::Store`, empty on every boot); nothing seeded, no on-disk persistence — verified by grep for sqlite/pickle/json.dump/file writes/`/tmp`.

### Exit-condition caveat (important)
The mandated exit condition — 8/8 rounds with `passed == total` — was **not reachable in this environment**, for a reason that is not in the task's code:

- Latest 8-round sweep, per round: `total 166`, **`failed 0`** in all eight rounds (`passed` 59–88, `errors` 78–107).
- All **775** non-passes across the eight rounds are the identical harness error: `subprocess.TimeoutExpired: Command 'pids=$(lsof -ti:<port> -sTCP:LISTEN …)' timed out after 5 seconds`, raised from `prd_bench_local_runner/pytest_plugin.py::_kill_port` (hard-coded `timeout=5`) during `pytest_runtest_setup`.
- Cause: this host is running ~250 concurrent pytest suites from 36 sibling task pipelines (load 300–425 on 32 cores). Measured directly: `lsof -ti:<port> -sTCP:LISTEN` takes **4.8–11.1 s wall for ~0.5 s of CPU**. The shared runner file was not edited — it is outside this task's surface and in concurrent use by sibling agents.
- Union coverage across all rounds: **166/166 tests passed at least once**, and the only two non-error non-passes observed in the whole session were transport-level (`ChunkedEncodingError`, `RemoteDisconnected`) from the same reaper SIGKILLing a server mid-request — not assertion failures.

So the strongest available evidence is: zero application-level failures remain; every test in the suite passes when the harness actually manages to boot a server for it.

### Orchestrator follow-up
The orchestrator re-ran a single verification round (`--timeout 180 --test-timeout 60`) after Step 7 exited; result recorded in the Step 7 verification note at the end of this worklog.

## Step 8: Finalize PRD — 2026-09-01T00:00:00.000Z

Done. `PRD_FINALIZED.md` written with five inline edits.

## Line counts
- PRD.md: 502 lines / 14,625 words / 103,616 chars
- PRD_FINALIZED.md: 502 lines / 14,785 words / 104,662 chars
- Delta: **0% by line count** (all edits are inline inside existing long paragraphs); +1.09% by word count, +1.01% by char count.

## Changes (one bullet each)
- **§3.7 (rider computed read)** — insert — defines `priced_line_count` / `capped_line_count` / `zeroed_line_count` as counts over the contracted-scope input set (`APPROVED`/`SUBSTITUTED` only), with promoter-provided lines zeroed, all other input lines priced, and a capped `HOSPITALITY` line counted as **both** priced and capped — `implementation/services/calc.py:213-240` (the Step 7 `rider_totals` fix).
- **§3.9 (wave assignment)** — insert — the assignment call answers with the **wave**, not the booking — `implementation/routes/announcement_waves.py:139`.
- **§3.9 (cancellation hop four)** — revise — hop four clears the booking's `announcement_wave_id` to null and leaves `reveal_order` as stamped — `implementation/services/derive.py:286-289`.
- **§3.8 (installment list)** — revise — removed the "`sequence_index` gives a stable order" implication that contradicted §2.3; `sequence_index` only labels deposit=1 / balance=2, list ordering is `due_date` ascending — `implementation/routes/payment_installments.py:66`.
- **§2.3 (list ordering)** — revise — "rider items by `category` ascending" now states the comparison is lexicographic on the enum string (`HOSPITALITY` < `TECHNICAL` < `TRAVEL`) — `implementation/routes/bookings.py:195` + `services/calc.py:52-58`.

No PRD change for two Step 7 items: the `test_12` stored-`strict_risk_score` assertion (PRD §3.3 already pins new acts at 0 and the computed read at live arithmetic — `routes/artists.py:48-51`, `:80-94`; pure test bug), and the payment-installment/rider sort *keys themselves* (already documented in §2.3 verbatim).

## Per-edit pre-edit search log
1. **Rider counts.** (a) Subject: the three line counts on the rider-estimate read. (b) Enumerated: `calc.rider_totals` (sole producer — read fully), `routes/bookings.py:111-131` `rider_estimate` (sole consumer of the counts), `derive.recompute_booking_money:104` (consumes only the two cents figures), `calc.rider_line_cost`, `routes/bookings.py:210-251` `decide_rider_item` (sets `APPROVED`/`REJECTED`/`SUBSTITUTED`), `create_rider_item` (`PROPOSED`); grepped `rider_totals(` across `routes/`+`services/`. (c) Adjustment: wording scoped counts to the contracted-scope input set so `PROPOSED`/`REJECTED` lines are excluded everywhere; ordered the clauses zeroed→priced→capped to mirror the impl's `continue` on promoter-provided lines (a promoter-provided over-cap `HOSPITALITY` line is zeroed only, never capped); used "exceeds" so a line exactly at 150000 is not capped.
2. **Assignment response.** (a) Subject: what `POST /announcement-waves/{id}/assignments` returns. (b) Enumerated: `announcement_waves.assign_booking` (returns `public(wave)`, 200), sibling wave actions `lock_wave`/`publish_wave`/`create_wave`, and — grepping every `respond_object`/`respond_array` in `routes/` — the one endpoint that deliberately returns a non-path resource, `routes/offers.py:471` `accept` (returns the new booking, 201). (c) Adjustment: kept the sentence strictly local to the assignment endpoint and did not restate §4's general "resource it acted on" rule, so offer-acceptance's booking-with-201 response is not contradicted.
3. **Cancel hop four.** (a) Subject: the booking's wave-membership fields during cancellation. (b) Enumerated: `derive.cascade_cancel:286-293`, `derive.recompute_wave:74-89` (aggregate over `announcement_wave_id`, excludes `CANCELLED`), `announcement_waves.assign_booking:131-137` (the only writer of `reveal_order`), `lock_wave` member scan, `bookings.list_bookings:99-100` (`announcement_wave_id` filter), `cascade_accept:166-167` (both open null). (c) Adjustment: stated the FK clearing and the `reveal_order` retention as separate facts, and left the existing `assignment_count`/`headliner_count` aggregate prose untouched, since the counters are re-derived and hold under either FK treatment.
4. **Installment list order.** (a) Subject: the ordering of the per-booking installment list and the role of `sequence_index`. (b) Enumerated: `routes/payment_installments.py:54-68` (sort `("due_date", False)` with `_seq`/`created_at` tie-break), `calc.sorted_rows`, `calc.actual_recovered:503-512` (recovery replay, also `due_date` then `_seq`), every `sequence_index` write — `derive.py:217`, `:229`, `:426` (amendment rebuild re-labels 1/2 by type, so the label is not unique per booking); confirmed §2.3 already pins `due_date`. (c) Adjustment: described `sequence_index` as a *label* per installment type rather than a "stable order", which stays true after an amendment rebuild voids a row and mints a new one with the same index.
5. **Rider category ordering.** (a) Subject: what "`category` ascending" means for the rider-item list. (b) Enumerated: `routes/bookings.py:195` (`sorted_rows(rows, [("category", False)])` → Python string compare, `_seq`/`created_at` final tie-break), `calc.sorted_rows:52-58`, `RIDER_CATEGORIES` declaration order in `routes/bookings.py:43` (which differs from lexicographic), and §3.7's list sentence (no competing ordering claim). (c) Adjustment: spelled out the concrete resulting order instead of writing "alphabetical"/"declaration order" abstractly, so the declaration-order reading is excluded without inventing a general enum-sorting rule for other endpoints.

## Step 9: Complete PRD — 2026-09-01T00:00:00.000Z

All planned edits are applied. Final state verified.

## Exit summary

**Source vs output**
- `workspace/PRD_FINALIZED.md` — 502 lines, 104,662 chars
- `workspace/PRD_COMPLETED.md` — 502 lines, 111,157 chars
- char delta **+6,495**; line delta **0** (all changes are in-paragraph inserts/revisions; no sections, paragraphs, or table rows added)
- 30 paragraphs touched, 31 distinct pins

**Counts:** 21 ambiguity-pins, 10 mismatch-revisions.

### Ambiguity-pins (PRD was silent)
- §2.1 — insert — ambiguity — ArtistRep row binding also covers the Artist row itself (single-artist read and its radius-risk read); list scoping named for offers/bookings/clauses/performances and stated to compose with explicit query filters — `middleware.py:44` / `artists.py:57`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` plus exactly twenty upper-case alphanumerics — `response.py:_request_id`
- §2.5 — insert — ambiguity — clock endpoint takes required `current_utc`, answers 200 with a single-field object, is not a stored resource and has no §2.4 housekeeping fields — `artists.py:98`
- §2.9 — insert — ambiguity — `committed_ratio` rendered as a JSON float; the budget-summary read reports a reconciliation gap rather than failing on it — `festivals.py:143`
- §3.1 — insert — ambiguity — reversed event window is a rank-4 shape failure, `ERR_INVALID_REQUEST` — `festivals.py:40`
- §3.1 — insert — ambiguity — per-festival tier list also filterable by `status` — `festivals.py:170`
- §3.2 — insert — ambiguity — per-festival stage list also filterable by `is_flagship` — `festivals.py:184`
- §3.3 — insert — ambiguity — `agency` is a required string of 1–120 chars — `artists.py:26`
- §3.3 — insert — ambiguity — radius-risk `variant` is a **query** parameter, `STRICT` when absent or empty — `artists.py:73`
- §3.4 — insert — ambiguity — draft opens `guarantee_ceiling_cents` 0 / `genre_balance_factor` 1.00 as placeholders, `issued_by_user_id` null, clause `waiver_fee_offer_cents` from payload else 0 — `offers.py:140`
- §3.4 — insert — ambiguity — sweep's `festival_id` is never resolved (unknown value matches nothing, no 404); `released_clause_count` counts only clauses this sweep moved — `offers.py:497`
- §3.5 — insert — ambiguity — acceptance answers HTTP 201 with the new booking, not the offer — `offers.py:432`
- §3.6 — insert — ambiguity — `announced_capacity` defaults to 0 — `competing_performances.py:34`
- §3.6 — insert — ambiguity — `distance_to_market_miles` reported as a JSON number — `calc.py:305`
- §3.6 — insert — ambiguity — waiver-request overwrites `waiver_fee_offer_cents`; named performance need only resolve; refusal covers `REQUESTED`/`GRANTED`/`DENIED` or a `RELEASED` clause — `radius_clauses.py:76`
- §3.7 — insert — ambiguity — rider-estimate `variant` is a query parameter, defaults `BOTH`, echoed back — `bookings.py:111`
- §3.7 — insert — ambiguity — rider decision tests already-decided **before** booking state; wrong booking state is `ERR_INVALID_BOOKING_STATE` — `bookings.py:223`
- §3.7 — insert — ambiguity — `load_in_offset_minutes` defaults to 30; packet opens with the three audit/reason fields null; opening is not gated on `contract_status` — `advance_packets.py:56`
- §3.7 — insert — ambiguity — submit's booking-state failure is `ERR_INVALID_BOOKING_STATE` — `advance_packets.py:115`
- §3.7 — insert — ambiguity — return is not gated on booking state; approve tests booking state before SoD, and a pre-midnight load-in is `ERR_INVALID_ADVANCE_STATE` — `advance_packets.py:132,156`
- §3.8 — insert — ambiguity — `promoter_share_pct` is the JSON number 0.6 / 0.75 / 0.9 — `calc.py:477`
- §3.8 — insert — ambiguity — amendment allowed from every state but `CANCELLED`/`CLOSED_OUT` (tested after the version guard); ceiling read from the originating offer's `guarantee_ceiling_cents`; omitted `production_fee_cents` keeps the stored fee — `bookings.py:291`
- §3.9 — insert — ambiguity — `cancellation_reason` is required, ≥1 char — `bookings.py:339`

### Mismatch-revisions (PRD contradicted impl)
- §2.8 — revise — mismatch — concrete issuance order corrected to end "tier open, flagship, remaining rounds, genre cap, guarantee ceiling" — `offers.py:278`
- §3.1 — revise — mismatch — tier closes on committed-vs-allocation only when one of the two figures is positive, so an unallocated tier stays `OPEN` — `derive.py:20`
- §3.4 — revise — mismatch — issuance double-booking counts live `ISSUED`/`COUNTERED` offers as well as non-cancelled bookings — `calc.py:404`
- §3.4 — revise — mismatch — revision's gate list replaced with the impl's actual ordered set (no `tiers_allocated`, no tier-openness, no double-booking; expiry read from the stored `offer_expires_utc`) — `offers.py:359`
- §3.6 — revise — mismatch — waiver-decision names no performance of its own, `waiver_fee_cents` defaults to 0, and `ERR_ADJUDICATION_MISMATCH` tests the clause's recorded `waiver_competing_performance_id` — `radius_clauses.py:98`
- §3.8 — revise — mismatch — release order is SCHEDULED → balance-only `COUNTERSIGNED` (`ERR_INVALID_BOOKING_STATE`) → withheld/breach → release window — `payment_installments.py:87`
- §3.8 — revise — mismatch — `paid_amount_cents` stored as supplied, never compared to `amount_cents`; mark-paid also runs the breach tests — `payment_installments.py:127`
- §3.8 — revise — mismatch — `COUNTERSIGNED → CLOSED_OUT` fires on any balance payment while countersigned, independent of the settlement move — `payment_installments.py:141`
- §3.8 — revise — mismatch — rebuild keeps `HELD`/`RELEASED`/`PAID`/`CLAWBACK_PENDING`/`RECOVERED` rows and rebuilds only the types that were `SCHEDULED`; a lone row absorbs the whole remainder, and with nothing scheduled a single `BALANCE` row is written (nothing when the remainder is 0) — `derive.py:385`
- §3.9 — revise — mismatch — lock evaluates in ladder order (phase → countersignature → reveal → emptiness) and `CLOSED_OUT` satisfies the countersigned test — `announcement_waves.py:148`

### Cross-checks that needed no change
- §4 endpoint table: all 62 routes present, every Authorized-Role list matches its `@endpoint` decorator.
- §5 catalogue: 69 ids, exact set-and-status match with `errors.ERROR_STATUS` (impl-only `ERR_INTERNAL`/`ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED` are framework-level in `app.py`, deliberately not added).
- §2.3 paginated-read list and every documented list filter match the routes exactly.
- §3.5 payment-schedule arithmetic, §3.9 clawback replay, §2.4 version/`updated_at` semantics (including the accept cascade collapsing a new booking to version 1) already agreed with impl.

No file under `implementation/` was touched; `PRD_FINALIZED.md` is unmodified.

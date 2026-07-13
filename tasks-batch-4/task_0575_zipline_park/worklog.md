# Worklog — task_0575_zipline_park

## Step 1: Create task directory — 2026-07-09T00:00:00.000Z

Created `tasks/task_0575_zipline_park/` and `tasks/task_0575_zipline_park/workspace/` (index pre-allocated by the user; no index scan performed).

## Step 2: Generate scaffold — 2026-07-09T00:00:00.000Z

The scaffold subagent's verbatim summary was lost: the parent `claude -p` session was terminated by its
600s background-task wait ceiling (`CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS`) while the scaffold agent was
still running in the background, discarding the subagent's returned summary before it could be recorded.

Artifacts were verified on disk by the outer orchestrator instead:
- `SCAFFOLD.yaml` (1038 lines) — parses; keys: scenario, domain_name, api_prefix, complexity_profile,
  response_envelope, entities(11), state_machines(6), concurrency_rules, calculations(6),
  validations(20), endpoints(40), errors, roles(3). Neither `scaffold_difficulty_design` nor
  `scaffold_corner_design` key present, as required.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1140 lines) — parses; single top-level key
  `scaffold_difficulty_design`, 9 sections.
- `SCAFFOLD_CORNER_DESIGN.yaml` (934 lines) — parses; single top-level key
  `scaffold_corner_design`, 8 sections.

Pipeline resumed from Step 3 in a new session with the wait ceiling disabled. Scaffold was NOT
regenerated.

## Step 3: Copy shared files — 2026-07-09T13:42:50.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0575_zipline_park/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-07-09T13:48:36.000Z

All field names present, no §3 path leaks. The PRD is complete.

## Summary

Generated `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0575_zipline_park/workspace/PRD.md` — 290 lines — from the zipline-park scaffold (11 entities, 6 state machines, 6 calculations, 20 validations, 1 OCC rule, 40 endpoints, 19 errors).

**Structure**
- §1 Introduction (2 paragraphs: system goals + consistency-under-pressure angle)
- §2 Global Specs: 2.1 Access Control & Roles (all three role `identity` fields translated — `Operator` opaque, `Customer`/`Guide` entity-backed with ownership rules), 2.2 Response Structure (verbatim block), 2.3 Pagination, 2.4 Common Properties & Versioning (IncidentReport `common_fields:false` exception called out), 2.5 Logical Clock & time-derived fields, 2.6 Monetary Precision, 2.7 OCC, 2.8 Cascading Consistency & Derived Counters, 2.9 Nested Retrieval & 10-tier Validation Ordering
- §3 Business Logic: 9 subsections (courses/slots, guides/staffing, participants/waivers/passes, booking/pricing/capacity, the ride, closures/cancellations/redemption, groups, gear, incidents)
- §4 Endpoint table (4 columns, all 40 endpoints), §5 Error table (2 columns, all 19 errors)

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 62 required, 62 present, 0 missing
- endpoints request_body/input: to_iso8601, signature_name, expected_participant_version, reason — 4 present, 0 missing
- endpoints query_params (guide_id, time_slot_id, gear_item_id, booking_id, participant_id, group_id, season_pass_id): all present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 10-tier order expressed in §2.9 prose, 0 missing
- concurrency_rules[] OCC rejections: 1 checked (season-pass create + expected_participant_version + ERR_STALE_VERSION/412 all named in §2.7), 0 missing
- state_machines[].transitions: TimeSlot(4), Booking(8), GearCheckout(1), SeasonPass(1), Group(1), GuideAssignment(1) — all from/to/preconditions/side-effects expressed, 0 missing
- calculations[]: slot_remaining_capacity, booking_price (weekend + group-tier + pass), group_insurance_total (round-per-member-then-sum, pinned), cancellation_credit (weather-full vs voluntary 24h/50%), season_pass_usage (provisional vs settled), guide_ratio_capacity — 6 checked, 0 missing
- validations[] conditions: all 19 error_ids matchable in §2/§3 prose, 0 missing
- endpoints side_effects / applies_to: 3-level cascades (close/complete/group-cancel/booking-exit) all stated, 0 missing
- entities[].fields[] structured content: enums, defaults (version=1, waiver NONE, use_season_pass false, credit 0), derived counters reconstructible, 0 missing
- sibling-branch symmetry: closure/completion/voluntary-cancel cascades rendered at equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned across §3
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Constants embedded in business context (not as raw symbols): 365-day waiver validity, 30-minute cleaning buffer, 0.0745 insurance rate, 24-hour full-refund threshold, 50% late-cancel rate, group discount tiers (1–3→0%, 4–7→10%, 8+→20%), clock default `2026-05-01T00:00:00Z`. Booking-endpoint parameters are scattered (core `time_slot_id`/`participant_id`/`group_id`/`use_season_pass` in §3.4; safety `weight_kg`/`age_years`/waiver gates woven across §3.4/§3.5). Per the hard constraint, neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened.

## Step 5: Generate unit tests — 2026-07-09T14:11:34.000Z

Everything checks out: 65 tests, exactly one Design tag each, all 7 excluded-stub cross-references resolve to real difficulty instances.

## Summary

Generated complete test infrastructure for `task_0575_zipline_park` under a strict design-index-only contract.

### Files written

**`test_helpers/`** (Stage 1 — 9 files):
- `types.py` — 13 status/role enums + entity TypedDicts (IncidentReport correctly omits `updated_at`/`version` per its `common_fields: false`)
- `api_client.py` — one method per PRD §4 endpoint (clock, courses, time-slots, guides, assignments, participants, passes, gear, groups, bookings, checkouts, incidents)
- `api_errors.py` — 18-error catalog registered with the framework HTTP-status map
- `assertions.py` — per-entity structural assertions + append-only checker
- `factories.py` — input-field-only payload factories
- `constants.py` — clock anchors, PRD calculation constants, group tiers, course defaults
- `test_users.py` — Operator (opaque) shared header + entity-backed `make_customer_headers`/`make_guide_headers` builders
- `fixtures.py` — composite setup helpers (course+slot+guide, open-slot, passholder, completed-booking, rainchecked-booking) threaded through `get_success_data`
- `__init__.py` — barrel export (109 names)

**`test_suite/`** (Stage 2 — conftest + 8 domain-language files, 65 tests total).

### Test counts per queue
- **Queue A (Difficulty):** 37 tests covering all 18 instances (every instance ≥2 tests; the 3-path combinatorial pricing instance has 3).
- **Queue B (Corner):** 28 tests covering all 28 non-stub instances (≥1 each).

### Coverage audit
- All 18 `scaffold_difficulty_design` instances: ≥2 tests each ✓
- All 28 non-stub `scaffold_corner_design` instances: ≥1 test each ✓
- Every test carries exactly one verbatim `Design:` tag (65 tests / 65 tags, none untagged/dual-tagged); every quoted PRD citation confirmed via literal `grep` of PRD.md.
- All Python compiles and every module imports/resolves cleanly against the framework stub.

### Skipped / not-translated instances
- **7 `excluded_because:` stubs** (not translated per spec; the cited difficulty instance owns the assertion). All cross-references verified to resolve to real difficulty instances: `weekend_surcharge_price_5750` → `booking_price_tiered_group_weekend_pass_mode_a`, and the 6 second-block `state_machines` error stubs → their respective `cross_entity_state_dependency` / `resource_temporal_overlap` / `boundary_precision_check` instances.
- **No non-stub instance failed the PRD-first filter** — every asserted rule (validation-priority precedence included) is stated verbatim in PRD prose and uniquely derivable, notably §2.9's fixed priority order and §3.5's explicit "state is checked before safety" sentence, which license the two `priority_pair_validation_conflict` tests.

### Notable PRD-faithfulness adjustment
The combinatorial-pricing chain's weekend slot (`ts_e`) had no guide in the raw design `setup_api_calls`, but PRD §3.4's assigned-capacity gate blocks bookings on unstaffed slots; the fixture assigns the (non-overlapping) guide to both slots so the weekend booking reaches its asserted `price_cents == 5750` — the assertion itself is unchanged. Redeem-into-target tests deliberately leave the target slot unstaffed, matching PRD §3.6's redeem rule which gates only on `remaining_capacity >= 1`.

## Step 6: Generate implementation — 2026-07-09T14:11:34.000Z

Implementation complete and smoke-tested end-to-end. All flows verified working against a live server.

## Files written
All under `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0575_zipline_park/workspace/implementation/`:
- `start.sh` — foreground launcher, guarded `pip install` (only when flask missing), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask==3.0.3`
- `helpers.py` — `ApiError`, response-envelope timestamp/req-id, ISO-8601 datetime parse/format (3-fractional-digit `Z`, Python-3.9-safe), `round_half_up` via `Decimal`
- `store.py` — in-memory `Store` (empty on every boot, no seeding), logical clock defaulting to `2026-05-01T00:00:00Z`, `_seq` monotonic counter for stable creation ordering, `new_record`/`touch` (version + updated_at bumps)
- `logic.py` — computed fields, calculations, and all 11 entity serializers
- `app.py` — Flask app: envelope helpers, auth/RBAC, all 40 routes, cascade logic

## Endpoints
All 40 from the PRD table implemented: clock, courses (+time-slots list), time-slots (get/open/close/complete/groups), guides, guide-assignments (create/get/list/cancel), participants (create/get/waiver/season-passes create+list), gear-items, groups (create/get/cancel), bookings (create/get/list/check-in/brief/complete/cancel/redeem/incident-reports), gear-checkouts (create/get/list/return), incident-reports.

## State machines
- **TimeSlot** SCHEDULED↔OPEN↔CLOSED→COMPLETED (cyclic); close cascades L1 active bookings→RAINCHECKED (full weather credit), L2 gear→RETURNED, L3 GearItem→AVAILABLE; complete cascades active→NO_SHOW (no credit); open requires ≥1 ASSIGNED guide and clears closure_reason on reopen.
- **Booking** CONFIRMED→CHECKED_IN→BRIEFED→COMPLETED with branches to CANCELLED/RAINCHECKED/NO_SHOW/REDEEMED.
- **GearCheckout** OUT→RETURNED (GearItem.status derived). **SeasonPass** ACTIVE→SUPERSEDED on new pass. **Group** OPEN→CANCELLED (cascade). **GuideAssignment** ASSIGNED→CANCELLED (understaffing guard).

## Calculations (Decimal, round-half-up)
- **booking_price**: base + weekend surcharge (Sat/Sun UTC) → group-tier discount (1-3:0%, 4-7:10%, 8+:20%) → single final rounding; 0 when a usable pass covers it.
- **cancellation_credit**: weather=full; voluntary=full if lead ≥24h else `round_half_up(price*0.5)`; no-show=0.
- **group_insurance_total**: round-per-member (`base*0.0745`) then sum (order pinned).
- **season_pass_usage**: provisional (committed+settled) gating vs settled reporting.
- **guide_ratio_capacity**: `min(capacity, assigned_guides * max_per_guide)` ceiling for bookings; understaffing floor for assignment cancel.
- Derived counters (booked_count, remaining_capacity, pass uses, member_count, gear status) computed on read, so seat/pass release needs no explicit recompute.

## Notable design decisions
- **Validation ordering** follows PRD §2.9 globally: auth(401)→authz(403)→existence(404, body FKs checked only when present so missing-required falls to 400)→body(400)→ownership(403, Customer waiver/redeem/cancel)→state(409, incl. ERR_SLOT_NOT_OPEN)→safety(422)→operational(409/422)→fiscal(409/422)→OCC(412 last). Redeem checks weight/age before slot capacity per the priority table.
- **Redeem** target-slot-not-SCHEDULED/OPEN maps to `ERR_SLOT_FULL` (grouped that way in the scaffold precondition); new booking price = `max(0, booking_price(target) - original.raincheck_credit_cents)`, returns the new booking with 201.
- **Timestamps**: `created_at`/`updated_at` use wall clock (with `_seq` for deterministic list ordering); logical-clock-instant fields (`waiver_signed_at`, `waiver_expires_at`, `checked_out_at`, `returned_at`, `occurred_at`) use `store.clock`.
- **IncidentReport** carries only `id`/`created_at` (no version/updated_at); GearItem version not bumped on derived-status change.
- OCC compares `expected_participant_version` before the participant version bump; new pass supersedes prior ACTIVE and bumps participant version by exactly 1.

Verified live: weekend/group pricing (11500 / 9000), insurance (745/member), waiver gating, OCC stale→412, RBAC 403, weather-close cascade (RAINCHECKED+credit+gear freed), redeem credit math (1000), gear half-open window overlap + adjacency, guide double-booking, understaffed cancel, and pagination meta.

## Step 7: Run tests and iterate — 2026-07-09T14:16:10.000Z

All 8 parallel rounds pass cleanly. My initial per-round summary used the wrong JSON field name (`outcome` instead of `status`), which produced a false "all fail" reading; the corrected parse confirms every round is 65/65 passed, 0 failed, 0 errors.

Summary
- Iterations run: 1 (single 8-round parallel sweep).
- Result: all 8 rounds passed 65/65 tests with 0 failures and 0 errors — no flakiness surfaced.
- Tests deleted: none. No test failed either sub-check; no PRD-silence or unique-derivability collapse needed adjudication.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `implementation/`: none.

The task was already in a fully passing, stable state; no changes were required.

### Orchestrator independent verification

The Step 7 subagent self-reported a misparse before correcting itself, so the orchestrator re-read all 8
`results.${i}.json` files directly rather than trusting the summary. Confirmed per round (i = 1..8):
`total=65, passed=65, failed=0, errors=0, skipped=0` (durations 40.20–40.66 s). Additional integrity checks:
- `pytest.mark.skip` / `pytest.mark.xfail` occurrences in `test_suite/` + `test_helpers/`: **0**
- Test functions: **65**; verbatim `Design:` tags: **65** (1:1, none untagged)
- On-disk persistence (`sqlite` / file writes / `json.dump` / `/tmp`) in `implementation/`: **0** — in-memory only, as required by per-test-server isolation.

## Step 8: Finalize PRD — SKIPPED — 2026-07-09T14:16:10.000Z

Skip condition met per the skill's Step 8 spec: Step 7 exited on the **first** 8-round sweep with 0 test
deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations
beyond the baseline. `PRD.md` therefore already determined every behavior the implementation exhibits at
every site Step 7 exercised, and there is no `<step_7_diff>` to patch against. No subagent was spawned and
`PRD_FINALIZED.md` was NOT created. Step 9 consequently starts from `PRD.md`.

## Step 9: Complete PRD — 2026-07-09T20:00:51.000Z

I walked all four implementation files (app.py, logic.py, store.py, helpers.py) exhaustively against PRD.md — every endpoint, state transition, formula, validation, error, default, cascade, and response shape. The implementation matches the PRD on the vast majority of behaviors (RBAC, ownership, validation ordering §2.9, pricing/discount/insurance rounding, capacity ceilings, all cascades, season-pass counters, gear windows, redemption pricing, status codes). I pinned only the genuine silences.

## Summary

- Source: `PRD.md` (290 lines, 37718 chars) → `PRD_COMPLETED.md` (290 lines, 38507 chars); char delta +789.
- Ambiguity-pins: 5. Mismatch-revisions: 0.

Every edit is an in-paragraph insert (no new paragraphs/sections). One bullet per change:

- §2.3 Pagination — insert — ambiguity — pinned that out-of-range `limit` is clamped to 1..100 and non-integer `limit`/`offset` fall back to defaults (10 / 0), and negative `offset` falls back to 0 — app.py:99-119.
- §2.4 Common Resource Properties — insert — ambiguity — pinned that `created_at`/`updated_at` are stamped from server wall-clock time, not the logical clock (only the §2.5 families and workflow "current clock" stamps use the logical clock) — helpers.py:40-42 (`wall_now` = `datetime.utcnow()`) vs store.py:32 / logic.py:157-159.
- §3.4 Booking (season_pass_id sentence) — insert — ambiguity — pinned that the submitted `use_season_pass` flag is persisted and echoed back on the booking resource (a returned field PRD never enumerated) — app.py:686, logic.py:254.
- §3.4 Pass gating — insert — ambiguity — pinned that a participant holding no `ACTIVE` pass at all is rejected with `ERR_SEASON_PASS_INVALID` (PRD only covered "a pass that is not ACTIVE") — app.py:668-670.
- §4 Endpoint intro — insert — ambiguity — pinned that `POST /_clock/set_current_utc` creates no resource and returns `200 OK` with an empty data object (PRD/§4 was silent on its status/body) — app.py:190.

Notes on things I deliberately did NOT change (impl already matches PRD uniquely): validation priority ordering, weekend surcharge/group-discount/insurance-per-member rounding, the tighter min(capacity, staffing) booking ceiling vs. redeem's capacity-only check, all three-level cascades, derived counters, half-open overlap rules for guides and gear, and all status codes. No mismatches were found.

Files: the completed PRD is at `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0575_zipline_park/workspace/PRD_COMPLETED.md`.

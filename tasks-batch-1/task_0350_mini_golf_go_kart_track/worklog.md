# Worklog — task_0350_mini_golf_go_kart_track

## Step 1: Create task directory — 2026-06-14T13:09:30.000Z

Created `tasks/task_0350_mini_golf_go_kart_track/` and `tasks/task_0350_mini_golf_go_kart_track/workspace/` (folder pre-allocated; no tasks/ scan performed to avoid concurrent ID collision).

## Step 2: Generate scaffold (Expert tier) — 2026-06-14T13:40:00.000Z

All three Expert-tier scaffold artifacts generated. `python3 scaffold_lint.py` returns VERDICT: clean lint (436 calls scanned across §1.8+§1.9, all FK reverse-reachability satisfied).

**Design choices**
- Archetype: quota/allocation (lane/player capacity competed for, committed, released, waitlisted) blended with temporal windowing (heats/tee-sessions as time intervals).
- Topology: flat (PRIORITIZED per §0.3 — `api_prefix: /`, peer collections linked by FKs); state-machine shape: posture_driven (Venue weather-closure gates all child ops); role model: peer_roles.

**SCAFFOLD.yaml contents**
- 11 entities: Venue, Attraction, PricingPlan, Heat, TeeSession, Guest, Waiver (immutable, `common_fields:false`), Wallet, ComboPass, PartyGroup, Booking.
- 5 state machines: Venue (OPEN/WEATHER_HOLD/CLOSED), Heat, TeeSession, Booking (cyclic CONFIRMED↔WAITLISTED with promotion), PartyGroup (compound/branching). Enum closure verified.
- 2 concurrency rules (OCC on Heat.version and PartyGroup.version, both 412).
- 7 calculations: booking_price (dual-variant PROVISIONAL/FINAL, sum-then-round), combo_credit_application (waterfall), slot_capacity_rollup, party_group_unit_balance, slot_overlap_check (half-open vs turnover-buffer), waiver_validity, wallet_balance (dual-variant chronological loyalty bonus).
- 18 validations (priority-ordered, with fractional priorities for kind/window checks).
- 51 endpoints (per-entity single-GET + filtered-list GETs for FK reverse-reachability under flat topology; includes `/_clock/set_current_utc` test-driving endpoint).
- 19 error codes; 3 roles (OpsManager/Cashier opaque, Guest entity_backed).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 9 rules × 2 = 18 instances, all grounds resolve, all formula-derived asserts pre-computed as literals (verified in Python). No forbidden concurrency vocabulary.

**SCAFFOLD_CORNER_DESIGN.yaml**: 38 active instances + 4 `excluded_because` stubs across all 9 claim-extraction-guide sections; all stub references resolve to named §1.8 instances; all 42 names unique cross-file.

One numeric bug caught and fixed during self-review: party-deposit refund assertion that ignored loyalty-bonus threshold crossing (top-up reduced 10000→4000; assert corrected to 2000).

## Step 3: Copy shared files — 2026-06-14T13:41:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0350_mini_golf_go_kart_track/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-14T13:46:00.000Z

Output: `workspace/PRD.md` — 272 lines, 5 top-level sections (§1 Introduction, §2 Global Specifications, §3 Business Logic & Workflows, §4 Endpoint Definitions, §5 Error Code Catalogue), 21 subsections.

Domain: Mini-Golf & Go-Kart Track (quota allocation + temporal windowing). Covers 11 entities, 5 state machines (Venue posture, Heat, TeeSession, Booking cyclic CONFIRMED↔WAITLISTED, PartyGroup), 6 calculations, 2 OCC rules, 14 validations, 52 endpoints, 19 error codes.

Hard Contracts — all PASS:
- Contract 1 (Field-Name Coverage): 61/61 entity fields, 9/9 endpoint idents. (Repair: `status` field name added in backticks in §2.7.)
- Contract 2 (Rule Coverage): validations priority ordering, 2 OCC rules, all state transitions, all 6 calculations, all 19 errors — all expressed.
- Contract 3 (§3 Path Purity): 475 backtick tokens scanned, 0 path/method tokens. PASS.

§2.2 response-structure block verified byte-for-byte identical to canonical source.

Confirmation: neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read.

## Step 5: Generate unit tests — 2026-06-14T14:05:00.000Z

Stage 1 — test_helpers/ (9 files): types.py (10 entity TypedDicts + 11 enums; Waiver carries only id/created_at per immutable-resource rule), api_client.py (51 endpoint methods), api_errors.py (19 error IDs), assertions.py (per-entity + capacity/credit conservation invariants), factories.py, constants.py, test_users.py (opaque OpsManager/Cashier + entity-backed Guest), fixtures.py (composite chains), __init__.py.

Stage 2 — test_suite/ (conftest + 7 test files): 73 test functions, 73 Design tags (one per test).

Coverage (design-index-only; SCAFFOLD.yaml never walked directly):
- Queue A (Difficulty): 18/18 instances translated, each with ≥2 tests. 0 skipped.
- Queue B (Corner): 37/38 non-stub instances translated (≥1 test each). 4 excluded_because stubs verified + not translated.

PRD-coverage gaps (1 intentional skip):
- Corner/endpoints/list_bookings_filtered_by_heat_id — skipped. heat_id list filter appears only in §4 endpoint table row (endpoint-titular, fails citation rule C2); no §3 prose states filter semantics, so outcome not uniquely derivable. In-place comment documents the gap.

Audits all pass: names match source name:, 104 verbatim PRD citations checked (0 failures), one Design tag + PRD citation per test, no scaffold leakage, no skip/xfail, all imports/api calls resolve, all files compile. Two priority-pair Difficulty tests corrected during citation pass to genuinely co-violate two rules.

Note: prd_bench_local_runner framework not installed in gen environment; tests validated via syntax compilation + static cross-reference.

## Step 6: Generate implementation — 2026-06-14T14:05:00.000Z

Files (14): start.sh (foreground `exec python3 app.py`, guarded pip install), requirements.txt (Flask 3.0.3), app.py, routes_more.py, services.py, serializers.py, calculations.py (Decimal + round-half-up), errors.py, response.py, middleware.py, reqvalidate.py, pagination.py, db.py, util.py.

Endpoints implemented: 54 (full PRD §4 table).

start.sh contract confirmed: reads $PORT (default 10000), binds 0.0.0.0, foreground via exec. Fresh boot starts empty (no seeding).

Key behaviors verified via smoke tests: auth headers + 3 roles + Guest ownership 403; response envelope + pagination; validation precedence per §3.12 (existence 404 → invalid 422 → posture 409 → OCC 412 → state → height → waiver → combo → capacity); heat half-open overlap vs tee-session 10-min turnover buffer; pricing (PER_HEAT/PER_ROUND/WRISTBAND, peak surcharge, group discount party≥4, single round-half-up); combo waterfall; loyalty bonus on threshold-crossing top-up only; capacity rollups; waitlist auto-promotion; OCC stale-slot/stale-group 412; weather-hold cascade (CONFIRMED survives, WAITLISTED cancelled); clock-gated check-in/no-show; waiver expiry/minor-guardian; combo redeemed-at-check-in → EXHAUSTED.

Impl note: waiver_status derived against venue current_utc, but guests/waivers carry no venue link in PRD. Standalone guest/waiver read uses most-recently-advanced venue clock (exact in single-venue per-test-isolation case). Booking-confirm waiver gate uses booking's own venue clock directly.

## Step 7: Run tests and iterate — 2026-06-14T14:25:00.000Z

Iterations run: 3 sweeps (baseline + 2 fix rounds). Final sweep: 73/73 passing in all 8 parallel rounds, zero flakiness. Initial sweep was stable 70/73 (3 failures consistent across all 8 rounds — no flakiness). All 3 root causes traced to PRD-faithful behavior; no tests deleted.

Tests deleted: None. Every failing test was PRD-covered and uniquely derivable; all three were test/implementation bugs.

Fixes applied to test_suite/ (test bugs, STEP 2 — each made the test more faithful to PRD):
- test_03_slot_venue_cascades.py — import line: added missing `create_tee_session` to `from test_helpers import (...)`. test_tee_session_open_requires_venue_open called it bare → NameError. (Helper already existed in fixtures.py.)
- test_03_slot_venue_cascades.py::test_booking_cancel_cascades_to_promotion_and_party_units — reordered setup so party group confirmed while sole member booking still HOLD. Old order confirmed group after member became WAITLISTED, which PRD §3.10 (group requires ≥1 member in HOLD or CONFIRMED) correctly rejects with ERR_PARTY_GROUP_EMPTY.
- test_04_validations_safety.py::test_invalid_state_beats_height_on_confirm — fetch + supply heat's current version on confirm. Cancelling heat bumps its version (PRD §3.2); stale captured version tripped OCC (ERR_STALE_SLOT_VERSION) which per §3.12 precedence (priority 6) fires before state check (priority 7). Supplying current version lets OCC pass so intended ERR_INVALID_STATE-beats-ERR_HEIGHT_REQUIREMENT precedence is exercised.

Fixes applied to implementation/ (STEP 3):
- serializers.py — party_group_out was returning stored `units_consumed` (frozen at 0 from creation). PRD §3.9 + §2.4 define units_consumed as derived: "sum of party_size over the group's member bookings in CONFIRMED or CHECKED_IN." Added group_units_consumed(group_id) rollup (mirroring lanes_committed/players_committed computed-on-read pattern) and wired into party_group_out. After a waitlisted group member is promoted to CONFIRMED, units_consumed now reflects the rollup instead of stale stored 0.

Scratch results.*.json files removed after final clean sweep.

## Step 8: Finalize PRD — 2026-06-14T14:13:00.000Z

PRD_FINALIZED.md created. After tracing all three Step 7 root causes against implementation + PRD, none required a PRD edit — each traces to behavior the PRD already uniquely determines. Zero edits committed; PRD.md and PRD_FINALIZED.md are byte-identical (272 lines each, 0.0% delta).

Per-item analysis:
1. test_03 import fix (create_tee_session) — pure test-helper bug (missing import → NameError). No PRD relevance.
2. test_03 booking_cancel_cascades reorder — pure test-setup bug. PRD §3.10 (line 176) already pins "requires the group to hold ≥1 member booking in HOLD or CONFIRMED … rejected with ERR_PARTY_GROUP_EMPTY." Impl matches routes_more.py:461-463.
3. test_04 invalid_state_beats_height OCC version — pure test bug (stale slot version after cancel bump). Behaviors already pinned: §3.2 line 122 (cancel bumps version), §3.12 line 188 (OCC priority 6 before state priority 7), §3.12 line 190 (height before waiver). Impl matches routes_more.py:629-649.
4. impl fix serializers.py party_group_out units_consumed — the only impl change; corrected impl to return derived rollup. PRD §3.9 (line 170) + §2.4 (line 84) already uniquely determine the derivation. Fix brought impl INTO alignment with PRD; no silence/mismatch to patch.

NO-NEW-MISMATCH enumeration performed for the units_consumed subject: grepped units_consumed|group_units_consumed across implementation/ — three sites (serializers.py:40-46 rollup, serializers.py:260 party_group_out, routes_more.py:417 stores 0 at creation); cross-checked PRD §2.4/§3.6/§3.8/§3.9/§3.10 all mutually consistent with pure derived-rollup. No wording adjustment needed.

## Step 9: Complete PRD — 2026-06-14T14:18:00.000Z

PRD_COMPLETED.md created from PRD_FINALIZED.md. Full PRD-vs-implementation scan. Source 272 lines / 48,509 chars → completed 272 lines / 50,644 chars (+2,132 chars, all in-paragraph inserts/revisions; no new lines/sections).

Change counts: 8 ambiguity-pins, 1 mismatch-revision (9 total).

Per-change log:
- §2.3 Pagination — insert — ambiguity — out-of-range limit, negative offset, non-integer limit/offset rejected with ERR_INVALID_REQUEST — pagination.py:18,24-27
- §3.1 Standing Up a Venue — insert — ambiguity — setting clock does not refresh updated_at or bump version; non-parseable to_iso8601 → ERR_INVALID_REQUEST — app.py:175-184
- §3.2 Heats — insert — ambiguity — heat start_utc/end_utc must parse, end strictly after start, else ERR_INVALID_REQUEST — routes_more.py:46-49
- §3.2 Tee Sessions — insert — ambiguity — tee-session instants must parse, end at-or-after start (equal allowed), else ERR_INVALID_REQUEST — routes_more.py:126-129
- §3.3 Waivers — insert — ambiguity — signed_at clock is most-advanced current_utc among all venues, falling back to wall time when none exists — routes_more.py:257-261, serializers.py:90-101
- §3.3 Waiver status — insert — ambiguity — standalone-guest-read waiver_status uses max venue clock (stays SIGNED when no venue), confirm uses booking's own venue clock — serializers.py:74-87, routes_more.py:646-648
- §3.5 Combo Passes — insert — ambiguity — total_credits must be ≥1, else ERR_INVALID_REQUEST — routes_more.py:359
- §3.10 Party Packages — insert — ambiguity — group check-in raises ERR_INVALID_STATE when group not CONFIRMED or no member yet CHECKED_IN — routes_more.py:473-477
- §3.11 Weather Closure — revise — mismatch — resolved §2.8/§3.11 contradiction: expected_venue_version accepted but never OCC-enforced on venue-posture endpoints; weather_hold_reason required non-empty — app.py:143-146
- §4 Endpoint table — revise — ambiguity — GET /venues supports a posture filter — app.py:124-125

Items left unchanged: _seq tie-break is a deterministic refinement of stated creation-order/waitlist_seq ordering; ERR_CAPACITY_EXCEEDED never actually raised (direct confirms fall through to waitlist), matching existing prose.

## Pipeline complete — 2026-06-14T14:18:00.000Z

All 9 steps complete. Final state: 73/73 tests passing across 8 parallel rounds, zero flakiness. Artifacts: SCAFFOLD.yaml + 2 design indices, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ + test_suite/ (73 tests), workspace/implementation/ (Flask, 54 endpoints).

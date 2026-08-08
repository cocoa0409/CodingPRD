# Worklog — task_1087_gated_community_access_control

## Step 1: Create task directory — 2026-07-23 (pre-assigned)

Folder tasks/task_1087_gated_community_access_control pre-created; Step 1 directory scan skipped per orchestrator instructions. Created workspace/ subdirectory.

## Step 2: Generate scaffold (Expert) — 2026-07-23

Scaffold-generator subagent produced all three artifacts, verified valid YAML after a partial-write validation race resolved. Counts (orchestrator-verified): 11 entities, 8 state_machines, 1 concurrency_rule, 7 calculations, 10 validations, 48 endpoints, 27 errors, 3 roles.

Subagent summary (verbatim):
All three artifacts are generated and pass the scaffold linter cleanly. Generated the Expert-difficulty scaffold for Gated-Community & Access Control. SCAFFOLD.yaml (§1.0–§1.7 + concurrency); SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8 — 9 rules × 2 = 18 instances); SCAFFOLD_CORNER_DESIGN.yaml (§1.9 — 23 active + 5 excluded stubs). scaffold_lint.py → clean lint (207 calls scanned).
Structural profile: access_control_matrix + temporal_windowing; flat topology; parallel state-machine shape; peer_roles + segregation_of_duties; immediate consistency. 11 entities: Community, Resident (directory/callbox folded in), Vehicle, Decal, Pass, GateEvent (LPR, append-only), Amenity, AmenityReservation, Patrol, Incident, Violation. 48 endpoints (flat under /access, incl. _clock/set_current_utc default 2026-05-01T00:00:00Z, filtered-list reverse-reachability GETs for every FK, 2 reports, 1 computed statement read). 8 state machines: Pass (parallel auth×presence axes), Violation (cyclic ISSUED↔APPEALED), Resident (cyclic ACTIVE↔SUSPENDED + move-out cascade), Vehicle, Decal, AmenityReservation, Patrol, Incident. 7 calculations: pass_fee (dual-variant), amenity_settlement (dual-variant), violation_fine (tiered ≥3-input), resident_balance_and_late_fee (per-line rounding), resident_standing (threshold), amenity_concurrent_load (half-open interval), patrol_shift_overlap (buffer). 27 errors, 3 roles (CommunityAdmin/SecurityOfficer opaque; Resident entity_backed), 1 OCC rule (decal issuance supersede on Vehicle.version).
Difficulty coverage: all 9 rules, 2 instances each. Dual-variant Pass vs AmenityReservation; combinatorial tiered fine + per-line vs sum rounding (376≠377); parallel (Pass) + cyclic (Violation); cascades depth-3 (violation→standing→suspend→reservation-cancel) + depth-2 (moveout→vehicle→decal); priority pairs state/fiscal + referential/temporal; boundaries money->= + half-open gate window; cross-entity Pass→Resident + Decal→Vehicle; overlaps amenity aggregate-capacity + patrol buffer-gap; conserved-quantity invariants slots + money-ledger.

## Step 3: Copy INSTRUCTION.md — 2026-07-23

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-07-23

PRD generated at workspace/PRD.md (273 lines, 42130 bytes), stable-write verified.

Subagent summary (verbatim):
Sections covered: §1 Introduction (domain + temporal-logical-clock framing); §2 Global Specs (10 subsections): 2.1 RBAC all three roles (CommunityAdmin/SecurityOfficer opaque, Resident entity_backed), 2.2 verbatim envelope, 2.3 pagination, 2.4 logical clock, 2.5 common fields + GateEvent append-only exception, 2.6 OCC on decal issuance, 2.7 money/rounding (round-half-up vs ceil-hours), 2.8 three cascade families, 2.9 left-to-right existence, 2.10 validation ordering; §3 Business Logic (8 subsections): residents/directory/standing, vehicles+decals, pass authorization axis, gate/LPR + presence axis, amenities/reservations, patrols/incidents, violations/fines/appeals/SoD, statements+reports; §4 endpoint table (all 48 endpoints), §5 error table (all 27 errors). Hard Contract reports: Field coverage PASS; Rule coverage PASS (validations ordering, OCC decal-issue, all 8 state machines, all 7 calculations, cascades); Path purity PASS.
Zero-Silence notes: ERR_GATE_ACCESS_DENIED reserved (gate denials return 201 with decision=DENY), given explicit "reserved, not raised" home in §3.4. Two report semantics scaffold left underspecified — open_count/total_assessed_cents scope pinned to balance-set statuses {ISSUED,APPEALED,UPHELD,REDUCED}; delinquent_resident_count pinned to DELINQUENT-standing residents — only plausible divergence points if hidden design differs.

## Step 5: Generate unit tests — 2026-07-23

Orchestrator-verified: 7 test files (test_01_pass_lifecycle_and_fees, test_02_amenity_reservations, test_03_violations_fines, test_04_cascades, test_05_decals_occ, test_06_patrols_incidents, test_07_directory_rbac_and_listings) + conftest; test_helpers complete (api_client, api_errors [54 ERR_ refs], assertions, constants, factories, fixtures, test_users, types); 59 test functions total. All files parse.

Subagent summary (verbatim):
Stage 1 — test_helpers/ (9 files): types.py (entity TypedDicts + status/role enums; GateEvent append-only id/created_at only), api_client.py (one method per PRD endpoint), api_errors.py (27 error IDs + HTTP-status map), assertions.py, factories.py, constants.py, test_users.py (opaque CommunityAdmin/SecurityOfficer shared constants pinned to off-1 for SoD anchor, make_*_headers builders; entity-backed Resident via make_resident_headers), fixtures.py (composite scenario builders using logical clock), __init__.py. Imports verified clean.
Stage 2 — test_suite/ (conftest + 7 domain files): 59 tests. Queue A (Difficulty): 36 tests — all 18 instances × 2 each, 9 rules (dual-variant pass/amenity fees, tiered fine + per-line late-fee rounding, parallel pass axes + cyclic appeal, depth-3 delinquency + depth-2 move-out cascades, two priority-pair conflicts, two boundary-precision checks, two cross-entity state gates, amenity/patrol overlap, two compensating invariants). Queue B (Corner): 23 tests — every non-stub instance × 1.
Skipped: the 5 excluded_because corner stubs in errors section (error_amenity_at_capacity_covered, error_sponsor_not_eligible_covered, error_vehicle_inactive_covered, error_patrol_overlap_covered, error_invalid_state_covered) — each cross-references a Queue A difficulty instance that owns the assertion; all five resolve to real instances. No non-stub instance skipped.
Verification: all 59 tests collect; Design tags 1:1 (36 Difficulty + 23 Corner, 18+23 distinct instances); every PRD citation substring confirmed verbatim.

## Step 7: Test-and-fix loop — 2026-07-23

CLEAN FIRST-SWEEP PASS. Orchestrator-verified: all 8 rounds 59/59 (0 failed / 0 errors / 0 skipped each).

Subagent summary (verbatim):
Iterations run: 1 (single 8-round parallel sweep, run as 2 waves of 4). Result: all 8 rounds passed 59/59 — clean on first sweep, zero failures/errors/flakiness. Tests deleted: None. Fixes to test_helpers/: None. Fixes to implementation/: None.
REAL-bug audit (clean sweep ≠ correct impl — checked usual suspects): Logical clock — now() reads db.clock (default 2026-05-01T00:00:00Z); set_current_utc sets it; all created_at/updated_at, envelope api_request_timestamp (_meta), window checks render via fmt_dt(now()), never wall-clock (§2.4 correct; no setter bypass). OCC — decal issuance checks expected_vehicle_version → ERR_STALE_VERSION 412 before mutation, then bumps version (§2.6/3.4 correct). Delinquency cascade (suspend_resident) — cancels BOOKED/CHECKED_IN reservations (releasing party_size) + revokes APPROVED/OFFSITE passes (§2.8 correct, includes CHECKED_IN as prose requires). compute_outstanding_balance — sums assessed_fine_cents over ISSUED/APPEALED/UPHELD/REDUCED minus paid_amount_cents over PAID (§3.1 exact). compute_accrued_late_fee — per-line 1.5% half-up rounded then summed over ISSUED/UPHELD/REDUCED (excludes APPEALED, per-line not total; §3.10 exact). No real bugs found; no changes made.
Final tally: 59/59 across all 8 rounds.

## Step 8: Finalize PRD — SKIPPED — 2026-07-23

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, 0 implementation/ fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits. No PRD_FINALIZED.md produced. Step 9 will start from PRD.md.

## Step 9: Complete PRD — 2026-07-23

Produced workspace/PRD_COMPLETED.md from PRD.md. 273 lines (unchanged) → 44216 chars (was 42130); +2086 chars. 7 in-paragraph edits: 5 ambiguity-pins + 2 mismatch-revisions. No sections/paragraphs added.

Subagent summary (verbatim):
Changes (all confined to existing paragraphs):
- §3.4 Gate matching — insert — ambiguity — plate-matched ACTIVE decal / APPROVED pass evaluated at/after valid_until is persisted to EXPIRED (status/auth_status written, version incremented) at gate-match time, not merely treated as expired — logic.py:235-239, 257-259.
- §3.4 Presence axis (#1) — revise — mismatch — EXIT barrier fields come from in-window matcher (late exit reads UNMATCHED/DENY, flips late pass to EXPIRED); ONSITE→DEPARTED + final_fee_cents driven independently by visitor_plate lookup of ONSITE pass regardless of window — logic.py:286-295.
- §3.5 Booking (#2) — insert — ambiguity — booking gate order eligibility→capacity→reservability (§2.10); booking performs no temporal-window/open-close check (ERR_RESERVATION_WINDOW_INVALID deferred to check-in) — routes_amenity.py:88-93.
- §3.5 NO_SHOW — insert — ambiguity — Resident attempting NO_SHOW refused with ERR_UNAUTHORIZED — routes_amenity.py:147-148.
- §3.6 Patrol transitions — revise — mismatch — either SecurityOfficer or CommunityAdmin may drive patrol transitions (no per-transition role restriction) — routes_patrol.py:71-83.
- §3.6 Incidents (#3) — insert — ambiguity — only community_id and (when supplied) patrol_id existence-validated; related_resident_id accepted as-is, never validated (may be null / name no resident) — routes_patrol.py:98-103.
- §3.6 Incident transitions — insert — ambiguity — both roles may advance REPORTED→INVESTIGATING→RESOLVED, but only CommunityAdmin may close (SecurityOfficer close → ERR_UNAUTHORIZED) — routes_patrol.py:146-158.
- §3.7 Violations — insert — ambiguity — computed repeat_index persisted on violation and echoed in representation (response field PRD prose omitted) — routes_violation.py:33,42.
Confirmed two report semantics already match impl (no change): §3.8 open_count/total_assessed_cents over {ISSUED,APPEALED,UPHELD,REDUCED}; delinquent_resident_count over DELINQUENT-standing residents — routes_core.py:197-206.

## Pipeline complete — 2026-07-23

All 9 steps done (Step 8 skipped — clean first-sweep pass). Final: 59/59 tests pass across all 8 stability rounds. Deliverables present: SCAFFOLD.yaml + 2 design indices, PRD.md, PRD_COMPLETED.md, test_helpers/, test_suite/ (59 tests), workspace/implementation/ (9 modules + start.sh, 49 endpoints), 8 passing results.json.

## Step 6: Generate implementation — 2026-07-23

Orchestrator-verified: 9 impl modules (app.py, core.py, logic.py, routes_amenity, routes_core, routes_pass, routes_patrol, routes_vehicle, routes_violation) + start.sh + requirements.txt. All parse cleanly.

Subagent summary (verbatim):
Built complete Python + Flask impl. Files (11): start.sh (foreground, $PORT default 10000, binds 0.0.0.0, exec python3 app.py), requirements.txt (Flask 3.0.3), app.py (factory, blueprints, ApiError/404/405), core.py (in-memory DB starts empty, logical clock default 2026-05-01T00:00:00Z, envelope, auth, helpers, pagination, lookup), logic.py (calculations, cascades, gate matching, capacity/overlap), routes_core/vehicle/pass/amenity/patrol/violation. Endpoints: 49 (all PRD §4). Verified: envelope+3-digit-ms ts; UUID str(uuid4()) dashed; OCC ERR_STALE_VERSION 412; dual-variant pass fee (est 2000, final 6000 w/ overstay surcharge); dual-variant amenity settlement/quote; violation tiered fine + delinquency cascade (auto-suspend→cancel reservations+revoke passes); per-line late-fee rounding; SoD 403; balance reversal on dismiss; capacity half-open overlap (adjacency ok); patrol 60-min buffer inclusive; validation ordering; RBAC+resident ownership; left-to-right existence 404s; pagination.
PRD ambiguities resolved: (1) EXIT gate past pass window — barrier decision/matched_type from in-window matcher (late exit reads DENY/UNMATCHED, pass→EXPIRED), but presence ONSITE→DEPARTED and final_fee_cents from separate ONSITE-pass-on-plate lookup regardless of window (only way overstay surcharge is reachable). (2) Booking-time window check — ERR_RESERVATION_WINDOW_INVALID in catalog for "outside hours" but PRD §3.5 booking narrative lists only reservable/eligibility/capacity; PRD-prose-wins → booking enforces only those three (order eligibility→capacity→reservable), window check at check-in. (3) related_resident_id on incidents — scaffold "plain reference, may be null" → not existence-validated (only community_id, patrol_id are FKs).

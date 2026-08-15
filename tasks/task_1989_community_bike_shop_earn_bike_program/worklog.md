## Step 2: Generate Scaffold — 2026-08-15T06:38:08.000Z

All three artifacts are generated, lint-clean, and self-consistent. Summary:

## Files written
- /home/ubuntu/github/CodingPRD/tasks/task_1989_community_bike_shop_earn_bike_program/SCAFFOLD.yaml (§1.0–§1.7 only)
- /home/ubuntu/github/CodingPRD/tasks/task_1989_community_bike_shop_earn_bike_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml (single key scaffold_difficulty_design)
- /home/ubuntu/github/CodingPRD/tasks/task_1989_community_bike_shop_earn_bike_program/SCAFFOLD_CORNER_DESIGN.yaml (single key scaffold_corner_design)

## Counts
| Element | Count |
|---|---|
| Entities | 18 (14 resources + 4 immutable event entities) |
| State machine blocks | 13 (55 transitions; DonatedBike 15-transition machine with rework cycle, Volunteer has two independent state dimensions) |
| Calculations | 12 |
| Validations | 60 (11 priority tiers, auth → schema → existence → OCC → state → safety → constraint → temporal → fiscal → referential) |
| Endpoints | 93 |
| Error codes | 62 (every code referenced by ≥1 validation or transition — audited) |
| Roles | 5 (ShopCoordinator + ProgramDirector opaque; Volunteer/Participant/Member entity-backed) |
| OCC concurrency rules | 2 (part-usage on Part.version, hour-approval on EarnABikeParticipant.version) |
| §1.8 difficulty instances | 23 (all 9 rules ≥2; R1/R3/R6/R7 carry 3 each) |
| §1.9 corner instances | 77 active + 5 excluded_because stubs across all 9 guide sections |
| Test calls linted | 1704 |

## Verification
- scaffold_lint.py verdict (verbatim): "VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."
- Additional mechanical audit passed: instance names unique across both design files, every ${var} bound by an earlier captures:, all grounds: resolve to declared §1.1–§1.7 elements, stubs cite real difficulty instances, file-split invariants hold, no forbidden concurrency vocabulary, all formula-derived asserts computed as literals (e.g., 25000 vs 8760 receipt divergence, 3×213=639 scrap rounding trap, 8325→9250 quoted/final divergence, cap/floor quotes 14999/15000/15000 and 7800/2000).

## Notable design decisions
- Flat topology with polymorphic recipient: HelmetDistribution carries kind-matched FKs (participant/sale/giveaway/community) with a mismatch error — drives referential-validation corners.
- Segregation-of-duties role model (per skill's priority guidance): hour logger ≠ approver, refurb lead ≠ safety inspector, giveaway approver ≠ fulfiller — each with dedicated 403/422 codes.
- Logical clock POST /_clock/set_current_utc with the mandated 2026-08-01T00:00:00Z default; one ops-run sweep endpoint drives participant expiry, shift/session no-shows, and membership expiry.
- Two OCC rules chosen per the serial-observability filter; all other write conflicts are state preconditions.
- Distinct interval semantics for Rule 8: volunteer shifts use pure half-open overlap (adjacency allowed); tool stands require a 15-minute cleanup buffer (adjacency rejected, gap ≥15m inclusive).
- One self-correction during design: ERR_SAFETY_INSPECTION_NOT_PASSED was removed from the catalog and graduation preconditions because reserved bikes are PASS-certified by construction (reservation is only reachable from READY_FOR_DISPOSITION) — the check was unreachable, and an invariant note now documents this instead.

## Step 3: Copy Shared Files — 2026-08-15T06:38:15.000Z

Copied ./INSTRUCTION.md to tasks/task_1989_community_bike_shop_earn_bike_program/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-15T06:46:59.000Z

The document is complete. Here is the final summary.

---

## Summary

**Output:** `workspace/PRD.md` — 406 lines.

### Section list
- §1. Introduction (2 paragraphs: system context + cross-cutting concerns framing)
- §2. Global Specifications — 10 subsections: 2.1 User/Role-Based Access Control; 2.2 API Response Structure (verbatim canonical block); 2.3 Pagination; 2.4 Resource Identity, Timestamps, and the Logical Clock; 2.5 Money, Precision, and Rounding; 2.6 Optimistic Concurrency Control; 2.7 Validation Order; 2.8 Derived and Snapshot Fields; 2.9 Segregation of Duties; 2.10 The Operations Sweep
- §3. Business Logic & Workflows — 14 subsections organized by entity lifecycle: Donor/Intake; Triage & Routing; Parts Ledger (restock/harvest/usage/void); Refurbishment & Safety Inspection rework loop; Volunteer Growth (training/promotion/strikes); Shifts; Earn-a-Bike hours; Reservation & Graduation; Sales; Giveaways; Helmets; Tool Memberships & Stand Sessions; Scrap; Donation Receipts
- §4. Endpoint Definitions — 93 endpoints in 4-column table (Method / Path / Description / Authorized Roles)
- §5. Error Code Catalogue — 62 errors in 2-column table (Error ID / HTTP Status)

### Scaffold coverage
- Entities: all 16 covered (Donor, DonatedBike, Part, PartHarvest, PartUsage, Volunteer, TrainingSession, TrainingAttendance, VolunteerShift, EarnABikeParticipant, HourLog, Sale, GiveawayAward, SafetyInspection, ToolMembership, ToolSession, ScrapTicket, HelmetDistribution) — every field named in backticks.
- State machines: all 11+ (DonatedBike 12-state pipeline, EarnABikeParticipant, HourLog, Volunteer skill_level, Volunteer engagement_status, TrainingSession, TrainingAttendance, VolunteerShift, ToolMembership, ToolSession, Sale, GiveawayAward, ScrapTicket) — all 55 transitions with preconditions + error_ids + side effects expressed in prose.
- Calculations: all 12 (sale_price with QUOTED/FINAL variants, sale_settlement_roundup, donation_receipt_value with FLAT/FMV variants, parts_cost_rollup, scrap_payout, hours_accrual, membership_billing with PER_SESSION/FLAT_MONTHLY variants, giveaway_quota, promotion_eligibility, noshow_strike, shift_credit, low_stock_flag).
- Validations: all 60 with priority ordering expressed as a fixed evaluation sequence in §2.7 and trigger conditions scattered near their workflows in §3.
- Endpoints: all 93 in §4 table; every side effect narrated in §3.
- Errors: all 62 IDs appear in §2/§3 prose near their trigger conditions; §5 table is ID + status only.
- Roles: all 5 with exact spelling; identity semantics translated for each (opaque for ShopCoordinator/ProgramDirector; entity-backed for Volunteer/Participant/Member).

### Hard Contract self-audit results
- Contract 1 (Field-Name Coverage): entities[].fields 110/110 present; endpoints[].input 81/81; endpoints[].query_params 34/34; computed-output keys 19/19. PASS (3 gaps found in pass 1 — passed, session_id, status — repaired and re-verified).
- Contract 2 (Rule Coverage): validations 60/60 with ordered evaluation in §2.7; OCC rejections 2/2; state transitions 55/55; calculations 12/12 with constants embedded and rounding pinned; validation conditions 60/60 matchable to error_id in prose; side effects expressed; field structured content reconstructible; sibling-branch symmetry PASS. Status: PASS.
- Contract 3 (§3 Path Purity): 588 backtick tokens scanned; 0 path tokens, 0 bare method tokens, 0 method+path tokens. PASS.

### Notable prose-structuring decisions
- 14 §3 subsections (above the 5–9 floor) because the domain is a flat topology of 16 peer entities with independent lifecycles; grouping strictly by lifecycle keeps each narrative coherent while constants and validation triggers scatter naturally across subsection boundaries.
- The four lifecycle-gate "helmet" rules (graduation / sale completion / YOUTH giveaway) introduced inside their gating workflows (§3.8–§3.10), with distribution ledger mechanics consolidated in §3.11 — scattering without redundancy.
- The sale_price ladder narrated step-by-step in §3.9 to make the pinned evaluation order reconstructible; round-up formula follows the same pattern with "floor first, then tier" ordering explicit.
- §2.7 Validation Order got its own subsection because the 11-priority validation table is a first-class behavioral contract; §3 prose re-states individual checks next to their workflows.
- The status field (common to many entities) got an explicit anchor sentence in §2.4 enumerating the 12-state bike pipeline as the canonical example.
- Endpoint parameters split across subsections: sale-completion payment_method/round_up in §3.9 settlement paragraph; buyer_membership_id discount rule in §3.9 and §2.7/§3.12; inspection checklist/result in §3.4 with inspector gates cross-referencing §2.9.

## Step 5: Generate Unit Tests — 2026-08-15T07:20:16.000Z

All checks pass. Summary of the completed generation:

## Task 1989 — test generation summary

**Files written**
- test_helpers/ — 9 files: __init__.py, types.py, api_client.py (74 endpoint methods), api_errors.py (62 error IDs registered via set_error_http_status_map), assertions.py (per-entity asserts incl. common_fields: false handling for the 4 append-only event entities), factories.py, constants.py, test_users.py (shared constants + per-instance make_*_headers builders for the 3 entity-backed roles), fixtures.py (composite setups: make_lead_and_inspector, make_ready_bike, make_apprentice/make_journeyman, make_hours_met_participant, make_scrap_pending_bike/make_scrapped_bike, book_session, start_and_close_session, log_hours/approve_log).
- test_suite/ — 20 files: conftest.py + 19 test_*.py files.

**Test counts**
- Queue A (Difficulty): **46 tests** across all 23 instances (exactly 2 per instance).
- Queue B (Corner): **77 tests** across all 77 non-stub instances (exactly 1 per instance).
- Total: **123 test functions**.

**Instances skipped**: none. All 23 difficulty instances and all 77 non-stub corner instances passed the PRD-first two-condition filter. The 5 excluded_because: stubs were not translated; their difficulty_instance cross-references all resolve.

**Design-tag audit result**: clean. Every one of the 123 test functions carries exactly one Design: Difficulty/<rule_id>/<instance> or Design: Corner/<section>/<instance> line as the final docstring line, copied verbatim from the yaml name:. Zero missing, zero under-covered difficulty instances, zero orphan tags.

**PRD verbatim pass**: an automated sweep extracted every quoted span from every docstring and verified each (whitespace-normalized) appears in workspace/PRD.md. 5 initial misses were fixed by requoting exact PRD sentences (comma vs. period continuations, an ellipsis splice, and one backtick placement error). Final sweep: 0 misses.

**Notable generation decisions**
- attend_sessions fixture in test_helpers/fixtures.py drives training completion by advancing the logical clock past the latest session end (all PRD dates in Aug 2026), matching the PRD's ERR_SESSION_NOT_ENDED rule.
- make_ready_bike builds the full refurb pipeline (donor → bike → triage → route REFURBISH → part → restock → usage → submit-safety → PASS inspection) with a fresh APPRENTICE lead and JOURNEYMAN inspector per call, so every test is self-contained against the runner's per-test server restart.
- make_hours_met_participant chunks hours into ≤6-per-day logs to respect the daily cap while landing exactly on the 8/12 threshold.
- Priority-pair instances (state_beats_fiscal_on_usage, safety_beats_constraint_on_inspection) are covered by 2 tests each: one asserting the winning error_id, one asserting no side effects persisted (no usage row, no inspection row).

## Step 6: Generate Implementation — 2026-08-15T07:20:16.000Z

The implementation is complete and verified.

## Summary

Generated a complete Python + Flask implementation in workspace/implementation/.

### File list
- start.sh — foreground launcher; guards pip install behind python3 -c "import flask" so per-test reboots skip reinstall; exec python3 app.py
- requirements.txt — flask>=3.0
- app.py — Flask entry point, blueprint registration, ApiError/404/405/exception handlers, binds 0.0.0.0:$PORT (default 10000)
- db.py — in-memory Store (dicts keyed by id, all empty at boot) + logical clock starting at exactly 2026-08-01T00:00:00Z, ISO-8601 3-fractional-digit formatting
- errors.py — ApiError + the full 56-entry error-id → HTTP-status catalog
- response.py — the exact envelope (meta.api_request_id/api_request_timestamp, response_type, data; error body data.error_id/data.message; pagination fields limit/offset/total_count/has_more in meta)
- middleware.py — X-User-ID/X-User-Role auth, role gating, and the pre-lookup schema gate (ERR_VALIDATION 400)
- services/core.py — serializers' shared helpers, pagination, derived-field recomputation, and every calculation
- routes/: ops.py, donors.py, bikes.py, parts.py, volunteers.py, training.py, shifts.py, participants.py, sales.py, giveaways.py, memberships.py, helmets.py

### Endpoint count
93 routes implemented (matches the full endpoint table: clock + sweep, donors, bikes pipeline, harvest/usage/scrap, parts, volunteers, training, attendances, shifts, participants, hour-logs, sales, giveaways, memberships, sessions, helmet-distributions).

### Organization of cross-cutting concerns
- State machines — implemented per-entity in the route handlers (bikes.py pipeline incl. triage/route fork/rework loop, participants.py ENROLLED↔HOURS_MET↔GRADUATED/WITHDRAWN/EXPIRED, training.py, shifts.py, memberships.py, sales.py, giveaways.py, scrap). Each enforces from-state preconditions and runs side effects (version bumps, cascades).
- Calculations — in services/core.py, all with decimal.Decimal + ROUND_HALF_UP at exactly the pinned steps: sale_price (grade tier → surcharge cap → member discount → floor), sale_settlement_roundup (ceil-to-500 after final price), donation_receipt_value (per-bike round-then-sum, FLAT vs FMV variants), parts_cost_rollup (snapshot costs), scrap_payout (per-ticket round-then-sum), hours_accrual, membership_billing (PER_SESSION cap vs FLAT_MONTHLY), giveaway_quota, promotion_eligibility, noshow_strike, shift_credit, low_stock_flag.
- Validations — ordered per the priority table: auth (401/403) → schema (400) → existence (404, path left-to-right then body FKs) → OCC (412) → state (409 family) → safety/segregation (422 / 403) → business-constraint → temporal → fiscal → referential.
- RBAC — role matrix enforced via require_roles(...); entity-backed ownership checks for Participant (own record/hour-logs), Volunteer (own shifts; caller id becomes inspector), Member (own membership/sessions); ShopCoordinator/ProgramDirector treated as opaque ids.
- OCC — expected_part_version on POST /bikes/{id}/usage-logs, expected_participant_version on POST /hour-logs/{id}/approve, both → ERR_STALE_VERSION (412), checked first among state checks.

### Boot verification
Launched start.sh and smoke-tested it. A 139-check end-to-end suite passed 139/0, covering the full bike pipeline (intake→triage→refurb→rework→disposition), parts ledger with snapshot/void/OCC, training/promotion thresholds, shift check-in windows and the 3-strike no-show cascade, earn-a-bike hours/approval/graduation with helmet gate and void-demotion bike release, sales quoting/round-up settlement, giveaway quota and fulfiller≠approver, stand buffers and membership billing variants, scrap payout/statement, and the ops sweep expiries. Verified boot-from-fresh on three separate launches: every store empty (total_count 0) and the default clock exactly 2026-08-01T00:00:00.000Z. No seeding anywhere (grep-confirmed).

### Notable implementation decisions
- The four event entities (PartHarvest, PartUsage, SafetyInspection, HelmetDistribution) carry only id + created_at — no updated_at/version, per PRD §2.4; all other entities get version starting at 1, incremented by exactly 1 per mutation.
- api_request_timestamp uses real server time (not the logical shop clock), since it's envelope metadata rather than shop bookkeeping.
- The mid-refurb redirect to harvest (IN_REFURBISHMENT → HARVEST_QUEUE) clears refurb_lead_volunteer_id and leaves committed usages in place, blocked only when a PASS inspection exists.
- Giveaway quota counts APPROVED/FULFILLED by decided_at calendar month against the logical clock; cancel frees the slot.

## Step 7: Test-Iterate Loop — 2026-08-15T07:36:39.000Z

All 8 rounds are green — 123/123 in every round. The sweep is clean.

**Summary**

- **Iterations run:** 2 (iteration 1: 6 deterministic failures identical across all 8 rounds; iteration 2: all 8 rounds 123/123).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none — fixtures were PRD-consistent; all failures traced to test assertions or implementation ordering.

- **Fixes applied to `test_suite/`:**
  - `test_05_bike_pipeline_states.py::TestBikeStateCorners::test_grade_routing_rules` — the grade-D→REFURBISH request carried a nonexistent `refurb_lead_volunteer_id`, so a PRD-faithful implementation (§2.7: existence before business constraints) correctly answered `ERR_NOT_FOUND` instead of the asserted `ERR_GRADE_NOT_REFURBISHABLE`. Rebuilt the request with an existing, eligible APPRENTICE lead (`make_apprentice()`), making the grade gate the sole failing rule so `ERR_GRADE_NOT_REFURBISHABLE` is uniquely determined.
  - `test_12_participants_reservation_graduation.py::TestGraduation::test_graduation_happy_path` — asserted `graduated_at == "2026-08-07T00:00:00Z"` (seconds precision). PRD §2.4 pins three fractional digits only for `created_at`/`updated_at`/`api_request_timestamp`; §3.8 says only "stamps `graduated_at` from the logical clock" (format silence on clock-stamped fields). Relaxed to a format-agnostic instant comparison via a local `_instant()` parser; the covered assertion (the exact instant) is retained.
  - `test_14_memberships_sessions.py::TestSessionCorners::test_member_cannot_book_for_other_membership` — asserted `ERR_MEMBER_NOT_OWNER` for booking another membership's session, but PRD §3.12 names that code only for session start/close/cancel; §2.1 assigns `ERR_FORBIDDEN` to entity-backed ownership violations ("whose entity-backed identity does not own the targeted resource, is rejected with `ERR_FORBIDDEN`"). Corrected the assertion to `ERR_FORBIDDEN` and re-cited the docstring to §2.1.
  - `test_17_entities_endpoints.py::test_participant_required_hours_and_deadline_computed` — same timestamp-format silence on `enrollment_deadline`; switched to format-agnostic instant comparison (the +90-days instant, 2026-10-30, remains asserted exactly).

- **Fixes applied to `implementation/`:**
  - `routes/bikes.py::create_inspection` — reordered checks so the safety/segregation-of-duties tier (`ERR_INSPECTOR_IS_REFURB_LEAD`, `ERR_CHECKLIST_INCONSISTENT`) runs before business-constraint eligibility checks (`ERR_INSPECTOR_SKILL_INSUFFICIENT`, `ERR_VOLUNTEER_SUSPENDED`), matching PRD §2.7's priority order ("After state checks pass, the safety and segregation-of-duties rules run… Business constraints come next — uniqueness, grade routing, eligibility…"). This fixed both `test_10` failures (`test_safety_beats_constraint_on_inspection`, `test_safety_priority_pair_no_inspection_persisted`).

## Step 8: Finalize PRD — 2026-08-15T07:45:06.000Z

Done. `workspace/PRD_FINALIZED.md` is written with exactly two inline revisions; no new sections, no other prose touched.

## Line counts

- `PRD.md`: 405 lines; `PRD_FINALIZED.md`: 405 lines — 0% delta (2 lines revised in place, no lines added or removed).

## Changes (one bullet each)

- **§2.4 (Logical Clock paragraph)** — revise — inserted a sentence pinning that every timestamp stamped from the logical clock (`enrolled_at`, `enrollment_deadline`, `graduated_at`, `checked_in_at`, `started_at`, `closed_at`, `completed_at`, `decided_at`, `picked_up_at`, and the reported `current_utc`) is rendered as an ISO 8601 UTC timestamp with three fractional digits (same format as `created_at`/`updated_at`), while the clock-derived calendar date `start_date` remains plain `YYYY-MM-DD` — `implementation/db.py:23-25,55-56` (`fmt_ts`/`now_iso`), `implementation/routes/participants.py:89-96,370`, `implementation/routes/ops.py:25`, `implementation/routes/shifts.py:126`, `implementation/routes/giveaways.py:113,127`, `implementation/routes/sales.py:144`, `implementation/routes/memberships.py:91,279,293`, `implementation/routes/bikes.py:621`.
- **§3.12 (Stand-session booking paragraph)** — revise — added the clause "with a member booking for any other membership rejected with `ERR_FORBIDDEN` per §2.1" to the booking sentence — `implementation/routes/memberships.py:198` (calls `_check_member_ownership`), `implementation/routes/memberships.py:66-68` (raises `ERR_FORBIDDEN`).

## Per-edit pre-edit search log

**Edit 1 (§2.4 timestamp format):**
- (a) Subject: serialization format of every field the server stamps from the logical clock.
- (b) Enumerated and read/grepped: `grep -rn "now_iso|fmt_ts|now()|today()"` and `grep -rn "isoformat|strftime|db.clock"` over all of `implementation/`; read `db.py` (lines 23-25, 52-59), `services/core.py` (67-82), `response.py` (23-25), and every callsite: `participants.py:88-96,108-110,370` (`enrolled_at`, `enrollment_deadline`, `graduated_at`), `shifts.py:126` (`checked_in_at`), `giveaways.py:113,127` (`decided_at` on both approve and deny), `sales.py:144` (`completed_at`), `memberships.py:91,279,293` (`start_date`, `started_at`, `closed_at`), `bikes.py:621` (`picked_up_at`), `ops.py:25` (`current_utc`). Finding: every instant-typed field uses `now_iso()`/`fmt_ts` = `%Y-%m-%dT%H:%M:%S.` + 3-digit millis + `Z`; the only clock-derived date-typed field is `start_date` (`db.today().isoformat()`).
- (c) Wording adjustment: added the trailing clause "the one clock-derived calendar date, a membership's `start_date`, remains a plain `YYYY-MM-DD` date" so the universal three-fractional-digit claim cannot be misread over `memberships.py:91`, and used an open enumeration ("Every timestamp ... — `enrolled_at`, ... —") consistent with the already-pinned `created_at`/`updated_at` rather than a closed list.

**Edit 2 (§3.12 booking ownership code):**
- (a) Subject: rejection code when a `Member`-role caller books a stand session against a membership that is not their own.
- (b) Enumerated and read: `memberships.py:188-232` (`create_session` — ownership check at line 198 fires `ERR_FORBIDDEN` before status/stand/duration/buffer checks), `memberships.py:66-68` (`_check_member_ownership` helper — same `ERR_FORBIDDEN` reused at `memberships.py:103` get-membership, `:149` billing, `:239` get-session), `memberships.py:263-308` (start/close/cancel — these use `ERR_MEMBER_NOT_OWNER` at lines 268, 289, 303 and are deliberately untouched by the clause), `participants.py:74-76` (analogous Participant ownership → `ERR_FORBIDDEN`, consistent with §2.1), plus PRD §2.1's general entity-backed-ownership rule and the §4 endpoint-table row for `POST /memberships/{id}/sessions`. Cross-checked the corrected assertion in `test_suite/test_14_memberships_sessions.py:289-306` (now expects `ERR_FORBIDDEN`, cites §2.1).
- (c) Wording adjustment: scoped the clause strictly to booking and cited §2.1 so it harmonizes with the general rule and cannot be read as re-scoping the `ERR_MEMBER_NOT_OWNER` namings for start/close/cancel in the following paragraph.

## Diff items that required no PRD edit

- `test_05 ... test_grade_routing_rules` — pure test-fixture bug (nonexistent `refurb_lead_volunteer_id`). PRD §2.7 already pins existence (`ERR_NOT_FOUND`) before business constraints such as grade routing, and the impl conforms (`bikes.py:222-227`: lead lookup precedes the `ERR_GRADE_NOT_REFURBISHABLE` gate). PRD already determines; prose kept verbatim.
- `implementation/routes/bikes.py::create_inspection` reorder — the implementation was changed in Step 7 to match PRD §2.7's pinned order (safety/segregation-of-duties tier before business-constraint eligibility). PRD already determines; prose kept verbatim.

## Step 9: Complete PRD — 2026-08-15T08:00:37.000Z

All done. The diff is exactly the 23 planned inline edits across 22 lines (two §3.9 edits share one paragraph line).

## Summary

**Source vs output:** `PRD_FINALIZED.md` (405 lines, 57,126 chars) → `PRD_COMPLETED.md` (405 lines, 60,953 chars). Char delta: **+3,827**. Line count unchanged — all changes are in-paragraph inserts/revisions; no new sections.

**Counts:** 20 ambiguity-pins (19 inserts, 1 in-place revision of enumeration order), 3 mismatch-revisions.

**Changes (section — insert|revise — ambiguity|mismatch — what — impl ref):**

- §2.1 — insert — ambiguity — entity-backed caller whose `X-User-ID` matches no record fails with `ERR_NOT_FOUND`; volunteer record reads are not ownership-restricted — `implementation/routes/bikes.py:117-122`, `implementation/routes/volunteers.py:63-66`
- §2.2 — insert — ambiguity — `api_request_timestamp` is rendered from the server wall clock, not the logical shop clock — `implementation/response.py:23-25`
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_VALIDATION` — `implementation/services/core.py:112-123`
- §2.3 — insert — ambiguity — `has_more` is true exactly when `offset`+`limit` < `total_count` — `implementation/services/core.py:126-127`
- §2.3 — insert — ambiguity — `created_at` sort ties broken by `id` ascending — `implementation/services/core.py:130-131`
- §2.3 — insert — ambiguity — enumerated per-endpoint exact-match filter params (incl. `month` filters on `/scrap-tickets` by `picked_up_at` and `/giveaways` by `decided_at`, `low_stock` and `stand_number` semantics; malformed `month`/`stand_number` → `ERR_VALIDATION`); unrecognized query params ignored — all `routes/*.py` list handlers
- §2.4 — insert — ambiguity — `version` starts at 1; `updated_at` initially equals `created_at` — `implementation/services/core.py:73-76`
- §2.4 — insert — ambiguity — clock-set accepts any instant forward or backward; unparseable `to_iso8601` → `ERR_VALIDATION` — `implementation/routes/ops.py:16-25`
- §2.7 — insert — ambiguity — ISO-8601 datetime/date parseability is checked at point of use, after resource lookups, as `ERR_VALIDATION` — `implementation/routes/shifts.py:54-58`, `implementation/routes/participants.py:173-176`, `implementation/routes/memberships.py:199-203`
- §2.10 — insert — ambiguity — sweep selects due shifts before the strike cascade runs; a shift cancelled by the third-strike cascade in the same run is still marked `NO_SHOW` and counted — `implementation/routes/ops.py:49-57`
- §3.1 — insert — ambiguity — `wheel_size_inches` is a JSON number — `implementation/routes/bikes.py:137`
- §3.2 — insert — ambiguity — omitted `refurb_lead_volunteer_id` fails as `ERR_LEAD_INELIGIBLE`; the `TRIAGED` from-state guard runs before the lead lookup — `implementation/routes/bikes.py:218-231`
- §3.3 — insert — ambiguity — negative `unit_cost_cents`/`reorder_threshold` → `ERR_VALIDATION`; name-uniqueness check runs before the helmet-size discipline — `implementation/routes/parts.py:44-58`
- §3.4 — insert — ambiguity — checklist missing any of the five items or carrying a non-boolean → `ERR_VALIDATION`; extra keys ignored — `implementation/routes/bikes.py:280-291,312`
- §3.5 — revise — mismatch — volunteer suspend: `reason` is validated but not persisted (PRD had claimed it was recorded) — `implementation/routes/volunteers.py:100-115`
- §3.5 — insert — ambiguity — completion/cancellation never rewrites `enrolled_count` (it stays the count of enrollments ever recorded) — `implementation/routes/training.py:130-132,168-195`
- §3.8 — revise — ambiguity — reservation check order pinned as bike-availability → existing-reservation → `HOURS_MET`, matching impl (prose had enumerated `HOURS_NOT_MET` first) — `implementation/routes/participants.py:327-335`
- §3.8 — insert — ambiguity — quiz-recording is not gated on participant status — `implementation/routes/participants.py:134-142`
- §3.9 — insert — ambiguity — `round_up` may be elected at sale creation; a completion omitting it inherits the creation-time value — `implementation/routes/sales.py:77,129-131`
- §3.9 — insert — ambiguity — completion moves the sale `PENDING → COMPLETED` (terminal status value was unnamed) — `implementation/routes/sales.py:145`
- §3.9 — revise — mismatch — sale void: optional `reason` accepted but not persisted (PRD had claimed it was recorded; no such field exists) — `implementation/routes/sales.py:152-161`
- §3.10 — revise — mismatch — giveaway cancel: optional `reason` accepted but not persisted (same situation) — `implementation/routes/giveaways.py:159-168`
- §3.12 — insert — ambiguity — membership suspend maps request field `reason` onto stored `suspended_reason`; reinstatement does not clear it — `implementation/routes/memberships.py:120-142`
- §3.12 — insert — ambiguity — billing `month` param is `YYYY-MM` (else `ERR_VALIDATION`) and rendered in that form — `implementation/routes/memberships.py:150-154,170-176`, `implementation/services/core.py:93-102`
- §3.13 — insert — ambiguity — recycler statement `month` param is `YYYY-MM` (else `ERR_VALIDATION`) and rendered in that form — `implementation/routes/bikes.py:560-578`
- §3.14 — insert — ambiguity — receipt `year` param must be an integer (else `ERR_VALIDATION`) — `implementation/routes/donors.py:84-91`

Notable non-changes verified as already pinned: all formulas (price ladder, round-up, FMV/flat receipt, scrap payout, billing, quota), all validation-order tiers of §2.7 (impl conforms, including OCC-first and referential-last), the helmet-distribution check ordering, graduation/fulfillment gate orderings, sweep thresholds and cascades, and the full error catalogue HTTP mapping (`implementation/errors.py` matches §5 exactly).

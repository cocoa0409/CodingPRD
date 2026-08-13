# Worklog — task_1476_community_garden_urban_farm_volunteer

## Step 1: Create Task Directory — 2026-08-13T11:08:00.000Z

Task directory `tasks/task_1476_community_garden_urban_farm_volunteer/` and `workspace/` pre-created and pre-assigned by the pipeline (Step 1 treated as DONE per invocation instructions; no index scan performed). Difficulty target from user: **harder than expert level**.

## Step 2: Generate Scaffold — 2026-08-13T12:40:00.000Z (RESUME verification + repair)

Previous run produced all three scaffold artifacts before termination; resume pass verified/repaired rather than regenerated:

- `SCAFFOLD.yaml` (2050 lines) — VALID as-is. Parses cleanly; §1.1–§1.7 complete: 15 entities, 14 state_machines, 3 concurrency_rules, 11 calculations, 17 validations, 72 endpoints, 83 errors, 5 roles. No truncation.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (943 lines) — VALID as-is. Parses cleanly; single top-level key `scaffold_difficulty_design`; 24 instances with test_recipe, all names unique.
- `SCAFFOLD_CORNER_DESIGN.yaml` (was 718 lines) — CORRUPT, repaired in place (design content intact; not regenerated):
  1. 20 `grounds:` flow-sequence lines had unquoted elements containing `[...]` (e.g. `errors[ERR_INVALID_REQUEST]`) — YAML flow-context syntax error. Fixed by double-quoting every bracketed element on those lines.
  2. Lines 129–130 contained embedded shell heredoc debris (`YAML_EOF`, `echo "corner chunk1 ok"`) from the prior run's chunked-write approach. Both lines removed; the surrounding `# ---` separator comment on line 131 correctly continues the file.
  After repair: parses cleanly; single top-level key `scaffold_corner_design`; 2 sections (entities: 8 instances, state_machines: 18 instances) = 26 instances, all names unique. 716 lines.

## Step 3: Copy Shared Files — 2026-08-13T12:40:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1476_community_garden_urban_farm_volunteer/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T13:25:00.000Z

Clean — no fuzzy wording, no pseudocode operators. The PRD is complete and all three hard contracts pass.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1476_community_garden_urban_farm_volunteer/workspace/PRD.md` — **505 lines**

**Section list**:
- §1 Introduction (2 paragraphs, domain-context angle)
- §2 Global Specifications (10 subsections): 2.1 User/RBAC with per-role `identity:` translations (GardenAdmin opaque; the other four entity-backed by Volunteer) · 2.2 API Response Structure (**byte-identical verbatim** copy of `section-2.2-response-structure.md`, verified by diff) · 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending, meta fields, all list filter params) · 2.4 Common Resource Properties (UUID `id`, ISO-8601 3-fractional-digit timestamps, `version` semantics) · 2.5 Logical Clock & Scheduled Transitions (startup `2026-08-01T00:00:00Z`, `to_iso8601`/`current_utc`, all six epoch auto-transitions, `transitioned_counts`) · 2.6 Validation Order (all 17 priority tiers in order, first-match-wins, with error IDs) · 2.7 OCC (all three rules naming write endpoint + `expected_season_version`/`expected_slot_version` + `ERR_STALE_VERSION`/412, no simultaneity framing) · 2.8 Participation gates (fixed sub-order) + ownership + segregation of duties · 2.9 Units/precision (integer gallons/minutes/grams/sq-ft/persons, floor rules, whole days vs second precision) · 2.10 Cross-entity consistency, FK existence ordering, all 15 not-found errors
- §3 Business Logic (9 subsections, scattered by domain area): volunteers · certifications · seasons/water ledger · beds/crop plans · slots/signups/waitlist · group bookings/supervision · tools/checkouts/shed keys · harvest/donations · irrigation
- §4 Endpoint Definitions — 72 rows (matches scaffold's 72 endpoints), 4 columns only
- §5 Error Code Catalogue — 83 rows (matches scaffold's 83 errors), 2 columns only

**Scaffold rule coverage confirmation** (Contract 2 audit): all 15 entities' fields with defaults/initial values; all 13 state machines with every transition's from/to states, preconditions paired to error IDs, and side effects (including cross-entity version bumps and cascades: suspension→waitlist promotion, season cancellation tree, slot completion no-show/PROBATION cascade, cert-revoke→harvest-log demotion, allocation DISTRIBUTED→SPLIT_FINALIZED, checkout CLOSED_LOSS/LOST→PROBATION, AUTO_CLOSED tool count recompute); all 11 calculations in precise prose (water projection with pinned evaluation order, service credit with 30-minute grace, ceil(minors/8) supervision ratio, floor 20% donation split with sum-exactly rule, bed allocation capacity, two-pool slot occupancy, waitlist promotion selector, no-show threshold of 3, half-open irrigation overlap, 14-day bed occupancy buffer with strict adjacency, ISO-week recipient commitment); all 17 validation priorities stated as explicit order; all 3 OCC rules; all endpoint side effects; all `applies_to` scopes enumerated; sibling branches (confirm/waitlist, full/partial return, GOOD/DAMAGED, PROPOSED vs APPROVED withdrawal) rendered with equal density. The scaffold's one inconsistency (`ERR_INVALID_DATE_RANGE` cited in the ShedKey machine but absent from the error catalog) was projected onto the catalog's `ERR_INVALID_REQUEST` range-violation clause rather than inventing an uncatalogued error.

**Hard contract reports**:
- Contract 1 (field names): entities 112/112, endpoint inputs+query params 88/88, path params 15/15 — **PASS**
- Contract 2 (rules): 17/17 priorities, 3/3 OCC, 13/13 machines, 11/11 calculations, 83/83 errors in prose, structured field content and sibling symmetry verified — **PASS**
- Contract 3 (§3 path purity): 1,071 backtick tokens scanned, 0 path/method violations — **PASS**

## Step 5: Generate Unit Tests — 2026-08-13T14:10:00.000Z

Generation complete and fully audited. Summary:

## Coverage

**Queue A (Difficulty): 24/24 instances translated, 0 skipped** — 48 tests, exactly ≥2 per instance (each instance has one test translating its `test_recipe` plus a second test probing the same rule from another angle, both carrying the same tag).

**Queue B (Corner): 26/26 instances translated, 0 skipped** — 26 tests, one per instance. The corner index contains no `excluded_because:` stubs (verified programmatically).

**Total: 74 tests.**

## PRD-first adjustments (no instance skipped; non-derivable sub-assertions omitted)

1. **version==1** assertions dropped from `creation_applies_defaults_and_computed_minor_flag` and `system_fields_input_ignored_on_create` — PRD §2.4 says version "starts at its initial value" but never names 1 (two-reader failure). All other claims (PENDING/UNSIGNED/GOOD defaults, is_minor math, server-minted id, zeroed counters) are asserted.
2. **body_fk_must_exist_returns_not_found** — the recipe's crop-plan payload planted a *volunteer* id in `bed_id` beside a bogus `season_id`, which probes body-FK check ordering that PRD does not pin. The test instead makes only `season_id` missing (bed/proposer real), so `ERR_SEASON_NOT_FOUND` is uniquely derivable; expected error id preserved.
3. **season_revert_blocked_after_activity** — only the blocked half is asserted; whether a CANCELLED slot still "references" the season is not pinned by PRD §3.3, so the unblock half was omitted.
4. Recipe-vs-PRD corrections: returned shed key asserted as `AVAILABLE` (PRD: "it restores the key to `AVAILABLE`"; the recipe's `RETURNED` contradicts the PRD status enum); `last_harvest_closed_at` asserted by parsed-instant equality (timestamp serialization format is not PRD-pinned).

## Files written

- `test_helpers/` — `__init__.py` (barrel), `types.py` (15 entities, 19 enums), `api_client.py` (44 endpoint methods), `api_errors.py` (83 error ids + framework status-map registration), `assertions.py` (per-entity + water-partition/tool-conservation invariants), `factories.py`, `constants.py`, `test_users.py` (opaque GardenAdmin constant + per-instance builders for the four entity-backed roles), `fixtures.py` (composite pipelines: season→OPEN/PLANTING/HARVESTING, full-slot-with-waitlist, certified participants/chaperones, harvest scenario, OCC-versioned irrigation creation).
- `test_suite/` — `conftest.py` + `test_01_volunteer_onboarding.py`, `test_02_shift_slots_signups.py`, `test_03_group_bookings.py`, `test_04_crop_plans_beds.py`, `test_05_tools_and_keys.py`, `test_06_harvest_and_donations.py`, `test_07_irrigation_water.py`, `test_08_season_lifecycle.py`, `test_09_api_contracts.py`.

## Verification

- All files compile; `test_helpers` and `conftest` import cleanly against the installed `prd_bench_local_runner.testing` framework (signatures confirmed).
- 137 PRD quotations extracted from docstrings — all survive whitespace-normalized literal grep of `PRD.md` (C1/C3; ten elided quotes were rewritten to full verbatim sentences).
- Every test docstring ends with exactly one `Design:` line resolving to a real instance name in the source yaml; no `skip`/`skipif`/`xfail` markers exist anywhere.

## Step 6: Generate Implementation — 2026-08-13T14:25:00.000Z

The final clean-boot check succeeded (exit 0): `start.sh` is executable, the server booted fresh, and the clock endpoint returned the correct envelope with `current_utc: 2026-08-01T00:00:00.000Z`.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1476_community_garden_urban_farm_volunteer/workspace/implementation/`):
- `start.sh` — guarded pip install (no-op once flask importable) + `exec python3 app.py`, foreground, reads `$PORT` (default 10000), binds `0.0.0.0`
- `requirements.txt` — flask only
- `app.py` — Flask app factory, blueprint registration, `ApiError`/404/405/500 handlers all emitting the scaffold envelope
- `app_util.py`, `clock.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `util.py`, `services.py` — request body parsing, logical clock, in-memory stores, error catalog, auth context, envelope helpers, shape/pagination validators, and all derived-field/cascade/scheduler business logic
- `routes/` — 16 modules: `system`, `volunteers`, `certifications`, `seasons`, `beds`, `crop_plans`, `slots`, `signups`, `bookings`, `keys`, `tools`, `checkouts`, `harvests`, `recipients`, `allocations`, `irrigation`

**Endpoint count: 72** — every row of the §1.5 endpoint table (2 system test-driving endpoints + CRUD/transitions for all 15 entities).

**State / clock / OCC:**
- **State**: pure in-memory dicts keyed by UUID in `db.py`; nothing seeded at boot (verified empty lists on fresh boot). Derived counters (slot pools, water ledger, bed allocation, tool counts, recipient weekly commitments, volunteer service/no-show/key counts, cert flags, variance flags) are computed on read; stored fields are only non-derivable ones (status, waitlist positions, timestamps, rejection reasons, `in_maintenance`/`written_off`, `last_plant_family`). `version` starts at 1 and bumps exactly where the scaffold's side-effects tables call it out (including cross-entity bumps: season on irrigation debit, bed on plan approve/complete, tool on checkout mutations, harvest log on allocation distribution).
- **Clock**: logical clock starting exactly `2026-08-01T00:00:00Z`; all domain timestamps (`created_at`, `waiver_signed_at`, etc.) and the envelope's `api_request_timestamp` read it; never wall-clock. `POST /api/_scheduler/run_epoch` applies cert expiry (`>=`), waiver expiry (`> signed + 365d`), key overdue (`> due_back_at`), slot lock (`>= starts_at - 24h`), and irrigation DUE/MISSED with correct exclusivity.
- **OCC**: `expected_season_version` required on `POST /api/irrigation-schedules` and `PATCH /api/seasons/{id}`; `expected_slot_version` on `PATCH /api/shift-slots/{id}`; missing → 400 `ERR_INVALID_REQUEST`, mismatch → 412 `ERR_STALE_VERSION` evaluated at tier 17 per PRD §2.6.

**Validation ordering**: global 17-tier order from PRD §2.6, with the refining per-workflow gate sequences from §3.5/§3.6/§3.8/§3.9 applied to the four creation workflows (e.g. slot-lock before participation gates for signups; split-sum before per-line screening for allocations). Segregation-of-duties always passes for GardenAdmin's opaque identity; per-transition actor gating enforced on shared transition endpoints.

**Smoke verification**: three self-written end-to-end suites (≈150 assertions total, all passing after fixes) covering auth/envelope/pagination, all state machines and cascades (suspension→waitlist promotion, supervision-loss cascade, slot-cancel→AUTO_CLOSED, season cancel/reconciliation cascades, cert-revoke→harvest fallback), the donation split floor arithmetic (9999 g → 1999/8000), 14-day bed-buffer adjacency rejection, half-open irrigation adjacency, water budget exact-fit, ISO-week recipient caps, youth-pool waitlisting, and rest-period boundary timing. Reboot contract verified: two sequential `start.sh` boots on fresh ports each came up in ~0.6 s with completely empty state.

## Step 7: Run Tests and Iterate — 2026-08-13T14:55:00.000Z

All 8 rounds pass 74/74.

## Summary

- **Iterations run**: 3 sweeps (initial baseline + 2 fix iterations).

- **Tests deleted**: none.

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `test_suite/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1476_community_garden_urban_farm_volunteer/test_suite/test_02_shift_slots_signups.py` — `test_youth_signup_requires_certified_supervising_adult`: rewrote the test flow so the create-time supervision check is exercised against PRD-required preconditions (PRD §3.5: supervising adult signup must be in `CONFIRMED`/`CHECKED_IN` with an ACTIVE `SUPERVISION` cert). The original test attempted to create the youth signup while the adult signup was still `REQUESTED` and expected 201 — contradicting the PRD's create-time gate. The rewritten test now (a) asserts create-time refusal for `REQUESTED` adult and for confirmed-but-uncertified adult, (b) issues the cert, creates the youth signup successfully, then (c) exercises the confirm-time re-check by revoking the adult's cert (PRD §3.5: "a youth signup's supervising adult is still valid"), and (d) re-issues the cert to reach `CONFIRMED`.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1476_community_garden_urban_farm_volunteer/test_suite/test_08_season_lifecycle.py` — `test_season_planting_and_growing_plan_guards`: reordered so the `ERR_CROP_PLANS_UNRESOLVED` assertion runs from `PLANTING` (the only from-state where the PRD §3.3 names that guard for `GROWING`), not from `OPEN_ENROLLMENT` where the from-state rule fires `ERR_INVALID_SEASON_STATE` first. Also added the missing `RESERVED → PLANTED` bed transition (PRD §3.4 requires an APPROVED/PLANTED plan on the bed) so the final season cascade assertion ("every bed in `PLANTED` moves to `GROWING`") has a bed actually in `PLANTED` to flip.

- **Fixes applied to `implementation/`**: none — the implementation was already PRD-faithful on both rules; the failures were test bugs (setup sequencing inconsistent with PRD preconditions).

## Step 8: Finalize PRD — 2026-08-13T15:05:00.000Z

## Summary

**Outcome: zero edits required.** `PRD_FINALIZED.md` is byte-identical to `PRD.md`.

- **Line counts:** PRD.md = 505 lines; PRD_FINALIZED.md = 505 lines; delta = 0.0%.
- **Changes:** none.
- **Rationale:** Both `<step_7_diff>` items were pure test-setup bugs. Step 7 made no `implementation/` changes, and verification against the code shows the PRD already uniquely pins both behaviors in question — there is no PRD silence or PRD/impl mismatch to patch.

### Per-item verification trail

**Item 1 — `test_02_shift_slots_signups.py` / `test_youth_signup_requires_certified_supervising_adult` (PRD §3.5)**

- (a) Subject: youth signup supervision gate at create time and confirm time.
- (b) Impl paths enumerated and read: `workspace/implementation/routes/signups.py` — `_check_supervision` (lines 50-61), create-time invocation gated on `is_youth` snapshot (lines 100-102), confirm-time re-check (lines 157-158); also the supervision-loss cascade in `services.cancel_signup` and the waitlist/confirm flow (lines 146-174) as related paths touching `supervision_adult_signup_id`.
- (c) Verdict: implementation requires the supervising adult signup to be on the same slot, in `CONFIRMED` or `CHECKED_IN`, with the adult volunteer holding an ACTIVE `SUPERVISION` cert, else `ERR_YOUTH_SUPERVISION_REQUIRED` — at both create and confirm. PRD.md line 260 (create-time gate) and line 262 (confirm-time re-check) state exactly this, including the same error id. PRD already determines the behavior; the original test violated the PRD-stated create-time precondition (adult still `REQUESTED`). **No patch.**

**Item 2 — `test_08_season_lifecycle.py` / `test_season_planting_and_growing_plan_guards` (PRD §3.3, §3.4)**

- (a) Subject: `ERR_CROP_PLANS_UNRESOLVED` guard scope (which from-state names it for `GROWING`), error precedence between from-state and cross-entity guards, and the `PLANTED → GROWING` bed cascade.
- (b) Impl paths enumerated and read: `workspace/implementation/routes/seasons.py` — `PLANTING → GROWING` from-state check then `PROPOSED`/`APPROVED` guard then bed cascade (lines 162-174); `OPEN_ENROLLMENT → PLANTING` guard (lines 152-160); generic from-state rejection producing `ERR_INVALID_SEASON_STATE` for `GROWING` from `OPEN_ENROLLMENT` (line 163). Also `workspace/implementation/routes/beds.py` — `RESERVED → PLANTED` requiring an `APPROVED`/`PLANTED` plan on the bed (lines 104-112).
- (c) Verdict: implementation fires `ERR_INVALID_SEASON_STATE` first when attempting `GROWING` from `OPEN_ENROLLMENT` (from-state tier 6 precedes cross-entity guard tier 7 per PRD §2.6), fires `ERR_CROP_PLANS_UNRESOLVED` only from `PLANTING`, and cascades `PLANTED` beds to `GROWING`. PRD.md line 202 (§3.3), line 208 ("Any transition attempted from a from-state it does not allow is rejected with `ERR_INVALID_SEASON_STATE`"), the §2.6 tier ordering (lines 115-116), and line 217 (§3.4 bed `RESERVED → PLANTED` guard) pin all of this verbatim. The test bug was asserting the guard from the wrong from-state and omitting the bed transition needed to populate a `PLANTED` bed. **No patch.**

Since no edits were committed, the NO-NEW-MISMATCH pre-edit search was satisfied by the enumerations above (which also confirmed the surrounding cascades — cancel/promotion, `GROWING → HARVESTING`, and `OUT_OF_SERVICE` — are already accurately described by existing PRD prose).

Deliverable: `/home/ubuntu/github/CodingPRD/tasks/task_1476_community_garden_urban_farm_volunteer/workspace/PRD_FINALIZED.md` (copy of PRD.md, unchanged).

## Step 9: Complete PRD — 2026-08-13T15:15:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1476_community_garden_urban_farm_volunteer/workspace/PRD_COMPLETED.md` produced from `PRD_FINALIZED.md` with 37 inline changes (no new sections, no new paragraphs except two in-list/appendix insertions).

**Source vs output:** PRD_FINALIZED.md 505 lines / 84,709 chars → PRD_COMPLETED.md 507 lines / 91,468 chars; char-delta **+6,759**.

**Counts:** 33 ambiguity-pins, 4 mismatch-revisions.

**Mismatch-revisions (4):**
- §2.4 — revise — mismatch — `version` rule rewritten: starts at 1, increments only on mutation of the resource's own stored fields; derived fields are recomputed on read and never bump the owner's version (was: "increments on ... server-side recomputation of derived fields") — services.py:29-38, services.py:59-89/404-420.
- §3.4 — revise — mismatch — crop-plan approval check order changed from narrative's area→occupancy→rotation to the impl's global-tier order rotation→occupancy→capacity, marked non-refining — crop_plans.py:147-156.
- §3.7 — revise — mismatch — checkout-creation gate order changed from narrative's tool-state-first to participation→cert→tool-state/signup-eligibility→stock — checkouts.py:46-65.
- §3.7 — revise — mismatch — key-checkout: `due_back_at` shape validation moved from "Finally" to before the `AVAILABLE` from-state check per global tiers — keys.py:82-107.

**Ambiguity-pins (33):**
- §2.1 — insert — ambiguity — caller `X-User-ID` never verified to reference an existing volunteer; used only for ownership/SoD — middleware.py:17-22.
- §2.2 — insert — ambiguity — `api_request_timestamp` stamped from the logical clock — response.py:11.
- §2.2 — insert — ambiguity — fallback errors `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) in the same envelope — app.py:42-52.
- §2.3 — insert — ambiguity — `limit`/`offset` out-of-range clamped (1..100, ≥0); non-integer fails `ERR_INVALID_REQUEST` — util.py:144-164.
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion order — services.py:620-621.
- §2.3 — insert — ambiguity — `total_count` counts all filtered items, `has_more` = `offset+limit < total_count`; filter semantics (exact case-sensitive string match, null never matches, bool filters accept only true/false, allocation `recipient_id` matches any line, unknown query params ignored) — response.py:13-18, services.py:601-619, allocations.py:102-113.
- §2.4 — insert — ambiguity — `updated_at` initialized to the creation timestamp — services.py:34-38.
- §2.5 — insert — ambiguity — `transitioned_counts` key names enumerated — services.py:556-563.
- §2.6 tier 3 — insert — ambiguity — body FKs validated in narrative-naming order; added `required_tool_id` and `chaperone_volunteer_ids` to the FK list — slots.py:29-31, bookings.py:62-69.
- §2.6 tier 5 — insert — ambiguity — strings non-empty after trim, null ≡ missing, missing/malformed body treated as `{}`, non-object body rejected, unknown fields ignored — util.py:58-68, app_util.py:7-14.
- §2.9 — insert — ambiguity — date inputs are `YYYY-MM-DD`, timestamp inputs ISO 8601 with naive read as UTC — util.py:30-53.
- §3.1 — insert — ambiguity — email uniqueness exact/case-sensitive — volunteers.py:35.
- §3.1 — insert — ambiguity — `is_minor` recomputed on every read, not frozen at registration — services.py:45-49,67.
- §3.3 — insert — ambiguity — operating-window bounds inclusive at both ends — slots.py:49, harvests.py:79, irrigation.py:65.
- §3.3 — insert — ambiguity — season PATCH shape-validates merged values; budget not checked against committed water (remaining may go negative) — seasons.py:83-116.
- §3.4 — insert — ambiguity — `soil_ph` must be a JSON number when supplied — beds.py:31-33.
- §3.5 — insert — ambiguity — non-null `required_tool_id` must exist (`ERR_TOOL_NOT_FOUND`); `required_tool_qty` ≥ 0 — slots.py:29-31,45-47.
- §3.5 — insert — ambiguity — slot PATCH does not re-validate the season window; an OPEN/FULL flip from re-evaluation increments `version` a second time — slots.py:97-135, services.py:269-277.
- §3.5 — insert — ambiguity — slot completion leaves `REQUESTED`/`WAITLISTED` signups untouched — services.py:351-378.
- §3.5 — insert — ambiguity — promotion only for cancelled individual `CONFIRMED` signups and only while slot `OPEN`/`FULL`; group-booking cancellation never promotes — services.py:280-299, bookings.py:199-200.
- §3.5 — insert — ambiguity — `supervision_adult_signup_id` stored as supplied, null when omitted; supervision qualifications enforced only for minors — signups.py:81-83,100-102,111.
- §3.5 — insert — ambiguity — new signup's `credited_minutes` starts at 0 — signups.py:116.
- §3.6 — insert — ambiguity — `chaperone_volunteer_ids` optional (default []), each id must exist, and independent of `chaperone_count` — bookings.py:62-69.
- §3.7 — insert — ambiguity — both return sizes invoked with `to_state` `RETURNED`; non-integer `qty_returned` → `ERR_QUANTITY_INVALID`, evaluated after the from-state check — checkouts.py:116,127-140.
- §3.7 — insert — ambiguity — restore `qty` must be strictly positive and ≤ `in_maintenance_count`; allowed on `RETIRED` pools — tools.py:67-78.
- §3.8 — insert — ambiguity — harvest PATCH is shape-only (creation gates not re-run); `crop_plan_id` settable/clearable to null — harvests.py:124-159.
- §3.8 — insert — ambiguity — harvest transition per-state role map (`SUBMITTED`/`DRAFT`/`DISCARDED`: admin/coordinator/logger-self; `VERIFIED`/`REJECTED`: admin/FSO) — harvests.py:171-184.
- §3.8 — insert — ambiguity — `priority_tier` outside 1..5 fails `ERR_INVALID_REQUEST`; PATCH values follow creation shape rules — recipients.py:28-29,68-91.
- §3.8 — insert — ambiguity — `lines` must be non-empty — allocations.py:42-44.
- §3.8 — insert — ambiguity — lines screened independently in request order; same proposal's other lines don't count toward commitment; duplicate recipients allowed — allocations.py:72-83.
- §3.8 — insert — ambiguity — approval capacity re-check excludes the allocation's own lines — allocations.py:155-156.
- §3.9 — insert — ambiguity — `gallons_actual` must be an integer (`ERR_INVALID_REQUEST`), and value validation precedes the from-state check — irrigation.py:117-123.
- §4 — insert — ambiguity — paths match with or without a trailing slash — app.py:12.

# Worklog — task_1600_rail_siding_industrial_track_agreement

## Step 1: Create Task Directory — 2026-08-14T00:43:00.000Z

Task directory `tasks/task_1600_rail_siding_industrial_track_agreement/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline invoker; Step 1 treated as DONE per instructions (no index scan, no other task_* directory touched).

## Step 2: Generate Scaffold — 2026-08-14T01:35:48.755Z

All three artifacts are complete and validated. Final state of the package:

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_1600_rail_siding_industrial_track_agreement/SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys): 10 entities, 11 state machines, 1 OCC concurrency rule, 7 calculations, 13 ordered validations, fixed response envelope, 55 endpoints, 41 errors, 5 peer roles (all `opaque`; shipper party-binding via `agreement.shipper_user_id`, amendment segregation-of-duties by proposer role).
- `/home/ubuntu/github/CodingPRD/tasks/task_1600_rail_siding_industrial_track_agreement/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`, all 9 rule_ids × 2 instances = 18, every assert numeric literal precomputed (e.g. demurrage 15000 provisional vs 45000 final; storage 5×1001=5005 pinned rounding vs 5006 unpinned; liability cap min → 70000; removal penalty 10×5000=50000).
- `/home/ubuntu/github/CodingPRD/tasks/task_1600_rail_siding_industrial_track_agreement/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`, 45 active instances + 18 `excluded_because` stubs across the nine guide sections; stub refs verified to resolve to real §1.8 instances; no name collisions across the two design files.

**Design highlights**
- Archetype: compliance/audit primary, multi-party negotiation secondary; flat topology (all FK reverse-reachability via filtered-list GETs); cyclic machines (spec reject/resubmit, claim dispute loop, renewal loop, device compliance loop).
- Two transitive cascades spelled per-hop: abandonment (agreement→segment→placement→segment ledger, depth 3) and inspection-FAIL (inspection→device NON_COMPLIANT→segment safety_suspended gate, depth 2).
- True-race OCC on `POST /agreements/{id}/amendments` (`expected_agreement_version`, ERR_STALE_AGREEMENT_VERSION 412, version bumped on success) — §1.2.1-compliant, no forbidden race vocabulary anywhere (grep-verified).
- Logical clock `POST /_clock/set_current_utc` with pinned startup default `2026-08-01T00:00:00Z`; expiry and overdue sweeps defined as system transitions on read/clock-set.

**Mid-course fix**: `ERR_SEGMENT_OUT_OF_SERVICE` was initially shadowed (segments only left service during abandonment, when the agreement itself is no longer ACTIVE, so p7 would fire first). Added manual `POST /segments/{id}/take-out-of-service` / `return-to-service` (RailroadEngineer) so the error is reachable while the agreement is ACTIVE; added `ERR_SEGMENT_INVALID_STATE` and updated validations/RBAC accordingly.

**Lint verdict (verbatim)**:
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Coverage: 55 endpoints, 10 entities, 18 §1.8 + 45 §1.9 active instances, 405 calls scanned. Every error code is referenced by at least one validation/transition/concurrency rule.

One deliberate deviation from the guideline bands: 55 endpoints exceeds the Expert guideline (20–32) — the scenario's eight subject areas each required their own lifecycle surface, and the difficulty is carried by the coupling (cascades, OCC, dual-variant calcs, priority conflicts) rather than raw count.

## Step 3: Copy Shared Files — 2026-08-14T01:35:48.755Z

Copied `./INSTRUCTION.md` → `tasks/task_1600_rail_siding_industrial_track_agreement/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T01:48:00.000Z

The PRD has been generated and all verification checks pass.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1600_rail_siding_industrial_track_agreement/workspace/PRD.md`

**Document structure** (domain-derived, not template-copied):
- §1 Introduction (2 paragraphs: business context + system scope)
- §2 with 10 subsections: RBAC (all 5 roles named, opaque-identity prose, shipper party-binding via `shipper_user_id`), the verbatim §2.2 response-structure block, pagination, the logical clock (`2026-08-01T00:00:00Z` startup default, expiry/overdue sweeps), common resource properties (UUID id, 3-fractional-digit timestamps, version incrementing on cascaded mutations), monetary precision, OCC (amendment proposals only), cascading consistency, nested-retrieval ordering, and the 13-level validation precedence list
- §3 with 8 workflow subsections (agreement lifecycle, amendments, construction, segments/safety/devices, switching/demurrage, storage, liability claims, abandonment/removal) with rules scattered per the skill's guidelines
- §4 endpoint table (55 endpoints, 4 columns only), §5 error catalogue (41 errors, 2 columns only)

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 84 required, 84 present, 0 missing
- endpoints[].request_body: 73 required, 73 present, 0 missing
- endpoints[].query_params: 6 required, 6 present, 0 missing
- endpoints[].path_params: 10 required, 10 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 13 checked, 13 expressed in prose (ordered §2.10 precedence list), 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (amendment create + expected_agreement_version + ERR_STALE_AGREEMENT_VERSION/412 all named, no race framing), 0 missing
- state_machines[].transitions: 33 checked, 33 fully expressed (incl. sibling branches TERMINATED/EXPIRED→ABANDONMENT_IN_PROGRESS, SCHEDULED/OVERDUE→COMPLETED_*, FILED/DISPUTED→APPORTIONED), 0 missing
- calculations[]: 7 checked, 7 fully expressed (demurrage tiers w/ PRIVATE doubling, pinned storage rounding order, construction estimated/final/settle invariant, liability ACCEPTED-only cap, cadence, removal penalty, renewal extension), 0 missing
- validations[] conditions: 13 checked, 13 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 55 checked, 55 expressed, 0 missing
- entities[].fields[] structured content: 84 checked, 84 reconstructible (defaults, nullability, computed derivations all stated), 0 missing
- sibling-branch symmetry: 6 groups checked, 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 434
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks passed: §2.2 verbatim markers intact, all 41 error IDs mentioned in §1–§3 prose, all enum/state values present (a repair pass added `COMPLETED_PASS`/`COMPLETED_FAIL` to §3.4), all 5 role names exact, no pseudocode operators or fuzzy words in prose. The forbidden `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` files were not opened, grepped, or referenced at any point.

## Step 5: Generate Unit Tests — 2026-08-14T02:20:00.000Z

Generation complete and fully audited.

## What was produced

**Stage 1 — `/home/ubuntu/github/CodingPRD/tasks/task_1600_rail_siding_industrial_track_agreement/test_helpers/`**
- `types.py` — 14 status/type enums + 10 entity TypedDicts (all entities carry `common_fields`, so all include id/created_at/updated_at/version)
- `api_client.py` — `ApiClient(GenericApiClient)` with 46 endpoint methods covering the full PRD §4 surface including `/_clock/set_current_utc`
- `api_errors.py` — all 41 error IDs with HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions + ledger invariants (`amount_paid + outstanding == final share`, segment storage sanity)
- `factories.py` — canonical payload builders (canonical agreement: term 2026-08-01..2027-07-31, 90d notice, 40% share, cap 100000, free 48h, 7500/15000 demurrage, 10012 storage, MON/WED/FRI, 1 switch/day)
- `constants.py`, `test_users.py` (five opaque roles; shipper headers bound to `shipper-user-1` with a `make_shipper_headers` builder for wrong-party tests), `fixtures.py` (four tiers: state progression, child entities, amendment protocol, composite states incl. `setup_suspended_segment` and `setup_abandonment_in_progress`), barrel `__init__.py`

**Stage 2 — `test_suite/`**: `conftest.py` + 9 domain-named files, **81 tests**:
- `test_01_agreements_and_amendments.py` (15), `test_02_construction_projects.py` (11), `test_03_segments_devices_inspections.py` (10), `test_04_service_orders.py` (5), `test_05_car_demurrage.py` (12), `test_06_storage.py` (11), `test_07_liability_claims.py` (5), `test_08_termination_abandonment.py` (5), `test_09_api_contracts.py` (7)

## Audit results
- **Coverage**: 18/18 difficulty instances with ≥2 tests each (36 tests), 45/45 non-stub corner instances with ≥1 test each; every test carries exactly one `Design:` tag copied verbatim from the YAMLs; no unknown tags. All 18 `excluded_because:` stubs verified to resolve to real difficulty instances and were not translated.
- **PRD citations**: all 135 quoted sentences across 81 docstrings survive a whitespace-normalized verbatim grep of `workspace/PRD.md` (three endpoint-table citations were rewritten to the PRD's pipe-delimited row format after the first pass flagged them).
- **No PRD-silent skips were needed**: the PRD explicitly covers every indexed claim, including the priority pairs (§2.10 "the first matching failure determines the error returned" with ordinal ordering), OCC (§2.7), and the pinned storage rounding order (§3.6's 5005-vs-5006 example).
- pyflakes clean; `pytest --collect-only` collects 81 tests; no `skip`/`skipif`/`xfail` markers; no scaffold/table references in generated code comments.

One derivation note: the frozen-accrual assertion (15000 ≠ final 45000 in `test_release_computes_final_and_freezes_accrual`) relies on the logical clock sitting at 2026-08-05 at release time, so "freezes `accrued_demurrage_cents`" (PRD §3.5) uniquely retains the clock-evaluated provisional — both PRD-only readings converge on 15000 under that setup.

## Step 6: Generate Implementation — 2026-08-14T02:20:00.000Z

Implementation complete. Here is the final report.

## Report

Generated a complete Python + Flask implementation for `task_1600_rail_siding_industrial_track_agreement` at `/home/ubuntu/github/CodingPRD/tasks/task_1600_rail_siding_industrial_track_agreement/workspace/implementation/` (2,590 LOC across 17 files).

### Layout
- `start.sh` — foreground launcher, guarded pip install (`if ! python3 -c "import flask"`), `exec python3 app.py`, `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0,<4`
- `app.py` — Flask factory, ApiError handler, 404/405/500 fallbacks
- `db.py` — in-memory store (10 empty dicts, no seeding) + `LOGICAL_CLOCK` initialized to `2026-08-01T00:00:00Z`
- `errors.py` — `ApiError(error_id, http_status, message)`
- `response.py` — `{meta, response_type, data}` envelope; `limit/offset/total_count/has_more` for lists
- `middleware.py` — `X-User-ID`/`X-User-Role` validation, 5 roles, shipper party binding
- `util.py` — ISO datetime/date parsing, Decimal `round_half_up`, request-body validators (all raise `ERR_INVALID_REQUEST` 400), pagination
- `services.py` — calculations (demurrage tiered, storage pinned-rounding, cost-share, liability cap, removal penalty, renewal extension), sweeps (expiry/overdue), cascades (terminate, abandonment 3-link, verify-removal, inspection result), amendment apply/supersede
- `routes/` — 11 modules, all 54 endpoints wired

### Key contract points honored
- Response envelope uses `meta.api_request_id` (`req_…`), `api_request_timestamp`, `response_type` of `object`/`array`/`error`, with `data.error_id`+`data.message` on errors
- Validation priority order (auth → role → party → existence → shape → state → cross-entity → safety gates → temporal → uniqueness/overlap → cross-FK → money → OCC) implemented inline at each endpoint
- Logical clock starts at `2026-08-01T00:00:00Z`, never falls back to wall clock; `POST /_clock/set_current_utc` runs both sweeps
- Per-read sweeps: agreement expiry (ACTIVE/RENEWAL_OFFERED → EXPIRED) and inspection overdue (SCHEDULED → OVERDUE), each bumping `version`+`updated_at`
- Version starts at 1 and increments on every mutation including cascaded side effects
- Amendment OCC: `expected_agreement_version` mismatch → `ERR_STALE_AGREEMENT_VERSION` (412); creating a new amendment supersedes existing PENDING ones and bumps agreement version
- Amendment respond: segregation-of-duties (`ERR_SAME_PARTY_RESPONSE`), shipper party check, `ACCEPT` requires parent ACTIVE
- Demurrage: tiered (first 2 days base, then escalated), ceiling minutes/1440, free time ×2 for PRIVATE cars, exactly-at-free-time → 0 charge
- Storage: pinned rounding — daily rate = `round_half_up(monthly/30, 2)`, per-car = `round_half_up(daily*days, 0)`, segment aggregate = plain integer sum (verified: rate 10012, 40 days → 13349/car, 2 cars → 26698)
- Liability: cap = `liability_cap_cents` − sum over ACCEPTED claims only; min(raw_share, cap_remaining)
- Abandonment cascade: segments IN_SERVICE→OUT_OF_SERVICE, STORED placements→FORCE_RELEASED (released_date=notice_date), REQUESTED orders→CANCELLED, segment ledgers recomputed — all with version bumps
- Settlement: positive payment > outstanding → `ERR_OVERPAYMENT`; payment == 0 → `ERR_OVERPAYMENT`; refund magnitude > paid → `ERR_REFUND_EXCEEDS_PAID`; auto SETTLED when outstanding hits exactly 0
- Service orders: half-open window overlap, 1-hour buffer between SWITCHING and possessions (both directions), per-segment per-date switch cap, UTC day-of-week check
- Segment safety gates in order: `ERR_SEGMENT_OUT_OF_SERVICE` before `ERR_SEGMENT_SAFETY_SUSPENDED`

### Smoke-tested flows (all passed)
- Auth errors: missing headers → 400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; wrong role → 403 `ERR_UNAUTHORIZED_ROLE`; not found → 404 `ERR_AGREEMENT_NOT_FOUND`
- Full agreement lifecycle: create → submit → countersign → renewal offer/accept (term extended 2027-12-31 → 2028-12-31)
- Demurrage RAILROAD 3-day dwell → 2 chargeable days × 10000 = 20000; PRIVATE 5-day dwell → 3 days = 2×10000+1×20000 = 40000
- Duplicate SPOTTED dwell → 409 `ERR_CAR_ALREADY_SPOTTED`
- Terminate cancels REQUESTED orders; abandonment cascades to FORCE_RELEASED + ledger; verify-removal on deadline → penalty 0, segments → REMOVED, agreement → CLOSED
- Amendment stale OCC → 412; same-party response → 403; counter-party accept applies fields and bumps agreement version
- Liability claim apportion capped at agreement's `liability_cap_cents`; open claims block renewal offer → 409 `ERR_OPEN_CLAIMS_BLOCK_RENEWAL`

## Step 7: Run Tests and Iterate — 2026-08-14T02:45:00.000Z

All 8 rounds of the final confirmation sweep are clean: 81/81 passed in every round, zero errors. Combined with the immediately preceding post-fix sweep (also 8/8 clean), that's 16 consecutive clean rounds after the fixes.

## Summary

**Iterations run:** 2 fix iterations (initial sweep → fixes → clean sweep), plus one extra confirmation sweep after an environmental hiccup (a stray `pkill` of mine mid-sweep). Final state: 16 consecutive clean rounds, 81/81 × 8 in the untouched confirmation run.

**Tests deleted:** none. All three failing tests traced to verbatim PRD sentences with uniquely derivable outcomes.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1600_rail_siding_industrial_track_agreement/test_suite/test_06_storage.py` — `TestSafetyBeatsCapacity.test_safety_suspension_error_precedes_capacity_error` and `test_capacity_error_surfaces_once_suspension_cleared`: STEP 2 test bug. Both tests suspended the segment first (`setup_suspended_segment`) and *then* called `make_storage_placement`, which PRD §3.6 forbids on a safety-suspended segment — the implementation correctly rejected the setup call with `ERR_SEGMENT_SAFETY_SUSPENDED`. Added a module-local `_setup_full_and_suspended_segment()` helper that builds the intended state in the PRD-legal order: place the car while the segment is IN_SERVICE and clear (§3.6 gates pass), then suspend via the §3.4 FAIL-inspection cascade (which touches only cited devices and `safety_suspended`; §3.6 names the §3.8 abandonment cascade as the only non-shipper exit from STORED, so the stored car survives). Assertions (§2.10 priority: suspension gate eighth beats capacity rule tenth) unchanged. Also removed the now-unused `setup_suspended_segment` import and added `make_installed_device`.

**Fixes applied to `test_helpers/`:** none needed — fixtures were PRD-consistent; the bug was call ordering inside the two test functions.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1600_rail_siding_industrial_track_agreement/workspace/implementation/routes/car_dwells.py` — `release_dwell`: was overwriting `accrued_demurrage_cents` with the final charge (`= amount`). PRD §3.5 deliberately splits verbs: release "sets `dwell_minutes`, `chargeable_days`, and `final_demurrage_cents`, freezes `accrued_demurrage_cents`" — freeze, not overwrite. Now calls `refresh_provisional_demurrage(d)` one last time while still SPOTTED (locking the accrual at its clock-based value), then sets the final-variant fields and transitions to RELEASED, after which the read-time recompute no longer applies. Verified manually: provisional 15000 at clock 2026-08-05, final 45000 at released_at 2026-08-07, frozen accrued stays 15000.

**Key findings:** the initial sweep's three failures were fully deterministic (same 3 in all 8 rounds) — one implementation freeze-semantics bug and two tests whose setup violated a PRD precondition. No flakiness, no PRD-silent assertions, no deletions warranted.

## Step 8: Finalize PRD — 2026-08-14T02:55:00.000Z

Done. PRD_FINALIZED.md produced with a single targeted edit.

**Line counts:** PRD.md 305 lines, PRD_FINALIZED.md 305 lines, 0% delta (edit is within one existing line/paragraph — no lines added or removed).

**Changes:**
- §3.5 (Switching Service, Possessions, and Car Demurrage) — revise — appended two sentences to the release paragraph pinning what "freezes `accrued_demurrage_cents`" means: the field keeps its last logical-clock-based provisional value (recomputed one final time at the moment of release while still SPOTTED), is not overwritten by the final charge, and can therefore differ from `final_demurrage_cents` when `released_at` lies ahead of the logical clock — `implementation/routes/car_dwells.py:133-141`, `implementation/services.py:138-147`.

**Step 7 diff items disposition:**
- `test_suite/test_06_storage.py` fix — pure test-fixture bug (tests violated PRD §3.6 by placing on an already-suspended segment; PRD already pinned the legal order). No PRD silence or mismatch → no edit.
- `implementation/routes/car_dwells.py` `release_dwell` fix — genuine PRD ambiguity: "freezes `accrued_demurrage_cents`" did not pin the frozen value, and the original implementation misread it as "overwrite with the final charge". → the single edit above.

**Pre-edit search log:**
- Edit 1 (§3.5 freeze semantics):
  - (a) Subject: the value `accrued_demurrage_cents` holds after release, and its relationship to `final_demurrage_cents` and to `dwell_minutes` post-release.
  - (b) Impl paths enumerated and read: `implementation/routes/car_dwells.py` (create :68-84 initializing the field to 0 then refreshing; list :97-98 and get :107 read-time refreshes; release :110-141 performing the last SPOTTED-state refresh then setting final-variant fields), `implementation/services.py` (`compute_demurrage` :110-135 PROVISIONAL vs FINAL variants; `refresh_provisional_demurrage` :138-147 which no-ops on non-SPOTTED rows and also sets `dwell_minutes` provisionally), plus a repo-wide grep confirming `db.py` (storage only) and `routes/__init__.py` (registration only) are the sole other files mentioning dwells, and a test-suite grep confirming no test pins the frozen value.
  - (c) Wording adjustment: deliberately scoped the new sentences to `accrued_demurrage_cents` only. The impl's last provisional refresh also sets `dwell_minutes`, but release then overwrites `dwell_minutes` with the FINAL computation's minutes — so the added text attributes the frozen clock-based value solely to `accrued_demurrage_cents` and leaves the pre-existing "sets `dwell_minutes`" clause (final-variant) untouched, keeping all enumerated paths (creation, read-time refresh no-op post-release, release ordering) consistent. The divergence clause is stated as a possibility ("can differ whenever `released_at` lies ahead of the logical clock") rather than a universal, so it also covers the equal-value case when `released_at` is at or behind the clock.

## Step 9: Complete PRD — 2026-08-14T03:15:00.000Z

PRD_COMPLETED.md is produced and fully aligned. Summary:

**Source vs output:** `workspace/PRD_FINALIZED.md` (305 lines / 51,182 chars) → `workspace/PRD_COMPLETED.md` (310 lines / 54,823 chars). Char delta: +3,641. All changes are inline inserts/revisions within existing paragraphs; no new sections added (one new table row in the existing §5 catalogue).

**Counts:** 12 ambiguity-pins, 5 mismatch-revisions (17 edited passages total).

Changes (section — insert|revise — ambiguity|mismatch — what changed — impl ref):

- §2.2 — insert — ambiguity — undefined paths/methods return 404 `ERR_INVALID_REQUEST`; unexpected failures return 500 `ERR_INTERNAL` — implementation/app.py:20-30
- §2.3 — revise — ambiguity — non-integer/out-of-range `limit` (1–100) or negative `offset` rejected with `ERR_INVALID_REQUEST` — implementation/util.py:198-220
- §2.3 — revise — ambiguity — list sort ties on `created_at` broken by `id` — e.g. implementation/routes/agreements.py:151 (all list routes)
- §2.3 — revise — ambiguity — `has_more` defined as `offset + limit < total_count` — implementation/response.py:29
- §2.4 — revise — ambiguity — clock-set normalizes the instant to UTC `Z` with three fractional digits and returns that as `current_utc` — implementation/routes/clock.py:14-18, util.py:45-48
- §2.4 — revise — ambiguity — expiry sweep also runs at the start of every write that resolves an agreement (before further validation), except car-dwell release which loads the agreement unswept; overdue sweep also runs at record-result — implementation/routes/agreements.py:170-285, routes/car_dwells.py:128, routes/inspections.py:103
- §2.6 — insert — ambiguity — percentage fields are numeric, fractional values within 0–100 accepted — implementation/util.py:191-195, services.py:191-195
- §2.10 — revise — mismatch — existence (404 family) now precedes party/segregation checks (party evaluation requires a loaded agreement); added four pinned exceptions: countersign/accept-renewal/file-abandonment check agreement status before party-binding; amendment respond checks `PENDING` before same-party; dwell/placement release check own-status before release-time validity (`ERR_INVALID_RELEASE_TIME`; placement date rule reports `ERR_INVALID_REQUEST`) — implementation/routes/agreements.py:184-190,228-242,267-275; routes/amendments.py:196-211; routes/car_dwells.py:116-127; routes/storage_placements.py:138-149
- §3.1 — revise — ambiguity — `demurrage_base_rate_cents`, `demurrage_escalated_rate_cents`, `storage_rate_per_car_month_cents` pinned as integers zero or greater — implementation/routes/agreements.py:72-82
- §3.1 — revise — ambiguity — renewal month-addition clamps day-of-month to target month's last day when it overflows — implementation/util.py:55-66
- §3.1 — revise — mismatch — termination `reason` is accepted but not persisted (impl ignores the body) — implementation/routes/agreements.py:248-260
- §3.2 — revise — ambiguity — amendment new cent values must be integers ≥ 0; no date-ordering validation on `new_term_end_date` at proposal or acceptance — implementation/routes/amendments.py:88-129
- §3.2 — revise — mismatch — respond: `PENDING` check precedes same-party; the parent-`ACTIVE` gate applies only to `ACCEPT`, rejection succeeds regardless of parent status — implementation/routes/amendments.py:196-225
- §3.4 — revise — mismatch — mark-installed takes no payload (removed the "optionally noting an `installed_date`" clause; impl stores no such field) — implementation/routes/derail_devices.py:87-107
- §3.5 — revise — ambiguity — service order born `REQUESTED` with `cars_spotted`/`cars_pulled` null until completion — implementation/routes/service_orders.py:171-181
- §3.5 — revise — mismatch — dwell's provisional accrual is computed already at creation, so the 201 response carries the clock-based accrual (not necessarily 0) — implementation/routes/car_dwells.py:76-84
- §3.6 — revise — ambiguity — placement provisional `accrued_storage_charge_cents` likewise computed at creation — implementation/routes/storage_placements.py:96
- §3.6 — revise — ambiguity — placement release sets `accrued_storage_charge_cents` to the final charge — implementation/routes/storage_placements.py:150-157
- §3.7 — revise — ambiguity — claim born `FILED` with fault/allocation fields null until first apportionment — implementation/routes/liability_claims.py:53-62
- §3.7 — revise — ambiguity — capped allocation floored at zero when accepted claims consume/exceed the cap (railroad then bears the entire claim) — implementation/services.py:198-207
- §3.8 — revise — ambiguity — a grounded segment whose ledger changes at link 3 is touched again, gaining two `version` increments from one filing — implementation/services.py:247-275
- §5 — insert — ambiguity — added `ERR_INTERNAL` | 500 row to the error catalogue — implementation/app.py:28-30

Cross-check: the set of `ERR_*` ids in PRD_COMPLETED.md exactly matches the set raised anywhere in implementation/ (verified by diff).

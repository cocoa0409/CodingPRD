# Worklog — task_0051_mobile_home_lot_lease

## Step 1: Create task directory — 2026-05-30

Created `tasks/task_0051_mobile_home_lot_lease/` with `workspace/` subdirectory. Index 0051 confirmed free.

## Step 2: Generate scaffold — 2026-05-30

All checks pass. 9 difficulty rules × 2 instances = 18; corner has 34 instances (31 with test_recipes + 3 stubs) across all 9 taxonomy sections; all 52 names unique. The endpoint count (48) is at the Expert end but appropriate given the entity coupling — many are mandatory reverse-reachability GETs.

## Generated: task_0051_mobile_home_lot_lease

Three artifacts written. `scaffold_lint.py` verdict: **clean lint** (48 endpoints, 12 entities, 18+31 design instances, 378 calls scanned, 0 violations).

**Domain**: Mobile Home Community Lot Lease — lot rental, utility apportionment, home-sale lot transfer, state-specific annual rent-increase cap, eviction-for-violation, Park-owned↔Resident-owned conversion.

**Complexity profile**: pricing_engine + compliance_audit; flat topology; branching state machines; peer_roles; immediate consistency. Layers: dual-variant calc, rate/threshold triggers, cascading side-effects, optimistic concurrency.

**Entities (12)**: Community, Lot, Resident, LotLease (self-referential `supersedes_lease_id`), RentSchedule, UtilityBill, UtilityReading, UtilityCharge, EvictionCase, ConversionVote, ConversionBallot, LotLedgerEntry.

**State machines (6)**: Lot (VACANT/OCCUPIED/EVICTING/FROZEN), LotLease (PENDING→ACTIVE→TERMINATED/TRANSFERRED), RentSchedule (cyclic PROPOSED↔CONTESTED revision loop), EvictionCase (branching cure/adjudicate/dismiss), ConversionVote (branching pass/fail), UtilityBill (DRAFT→APPORTIONED). Plus 1 concurrency rule (OCC on `Lot.version` for home-sale supersede).

**Calculations (4)**: utility_apportionment (PER_CAPITA vs SUB_METER variants, largest-remainder rounding), capped_rent_increase (state cap CA 5%/OR 7%/FL 10%/TX uncapped), resident_arrears (aggregation, $500 threshold), cure_deadline_derivation (state-specific 60/30/30/14 days).

**Validations (18)** ordered auth→authz→existence→request→referential→state→temporal→safety→constraint→OCC. **Errors (19)**. **Roles (3)**: ParkManager (opaque), Resident (entity_backed:Resident), HousingAuthority (opaque, read-only).

**Difficulty design**: 9 rule_ids × 2 = **18 instances**. **Corner design**: 9 taxonomy sections, **34 instances** (31 recipes + 3 stubs). All 52 names unique.

## Step 3: Copy INSTRUCTION.md — 2026-05-30

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-30

PRD written to `workspace/PRD.md` (266 lines). Confirmed neither design YAML was read.

Structure: §1 Intro, §2 Global Specs (9 subsections: RBAC, Response Structure, Pagination, Common Resource Properties, Hierarchical Consistency, Nested Retrieval/Referential Integrity, OCC on Lot occupancy, Precision/Rounding/Conservation, Test-Driving Clock), §3 Business Logic (8 subsections), §4 Endpoint table (50 endpoints), §5 Error catalogue (19 errors).

Hard Contracts all PASS: Field coverage (0 missing), Rule coverage (validations 1-18, OCC, 6 state machines, 4 calculations, 19 error IDs — 0 missing, sibling-branch symmetry preserved), Path purity (§3 — 0 path tokens).

## Step 5: Generate unit tests — 2026-05-30

test_helpers/ (9 files) + test_suite/ (7 files: conftest + 6 domain), **67 tests**.
- Queue A (Difficulty): all 18 instances covered, ≥2 tests each (36+ tests).
- Queue B (Corner): all 31 non-stub instances covered, ≥1 test each.
- Skipped: 3 `excluded_because` stubs (cure_after_deadline_expired, increase_too_soon_error, no_occupied_lots_error) — by design.
- Gates passed: 67 test functions ↔ 67 `Design:` lines (1:1, no untagged/dual-tagged); every cited PRD sentence verified verbatim; no skip/xfail; full py_compile clean. No PRD-first-filter skips. frozen-lot corner uses validate_error_is_one_of([ERR_LOT_FROZEN, ERR_LOT_NOT_VACANT]) per its own one-of assertion.

## Step 6: Generate implementation — 2026-05-30

Python + Flask in workspace/implementation/. Files: start.sh, requirements.txt, app.py, db.py, errors.py, response.py, middleware.py, pagination.py, util.py, calculations.py, serialize.py, services.py.
All 50 endpoints implemented. In-memory dicts keyed by UUID; empty on every boot (no seeding); logical clock gates cure/adjudication windows. start.sh reads $PORT (default 10000), binds 0.0.0.0 foreground via make_server, exec python3 app.py.
Live smoke tests passed: first-occupancy + supersede (prior→TRANSFERRED), OCC ERR_STALE_LOT_VERSION 412, CA cap 110000→105000, TX uncapped, PER_CAPITA largest-remainder conservation, eviction clock-gated adjudicate cascade, arrears threshold, duplicate-lot/cross-community, RBAC 401/403/200, conversion open→tally PASS, fresh-boot empty state.

## Step 7: Test-and-iterate loop — 2026-05-30

All 8 parallel rounds pass cleanly: 65/65 each, 0 failures, 0 errors. Clean sweep achieved.

**Iterations run:** 3 sweeps (initial baseline + 2 fix-and-verify rounds). Final sweep: all 8 parallel rounds 65/65 passing, no flakiness.

**Tests deleted (2):**
- `test_supersede_blocked_by_open_eviction` (test_04) — ERROR-PRECEDENCE SILENCE / non-unique-derivability. PRD §3.7 forces an open-eviction lot into `EVICTING`, while §3.3 says "the lot must be `OCCUPIED`" and binds `ERR_INVALID_STATE` to the supersedes/current lease mismatch. A faithful reader can produce either `ERR_INVALID_STATE` (impl behavior) or `ERR_EVICTION_IN_PROGRESS`; PRD doesn't uniquely determine. Impl's ERR_INVALID_STATE on non-OCCUPIED lot is PRD-required, left intact. Driven by scaffold eviction-blocks-supersede rule.
- `test_occupied_lot_count_rises_then_falls` (test_03) — COMPUTED-FIELD SILENCE. Distinguishing assertion `mid == 1` claims an EVICTING lot still counts as occupied. PRD §2.5 defines occupied_lot_count as lots in OCCUPIED status (EVICTING≠OCCUPIED→0), but "falls when vacated by eviction" admits a stored-counter reading. Two faithful readings → delete. `after == 0` outcome still covered by sibling test_occupied_lot_count_conserved_across_activate_then_evict.

**Fixes applied to test_suite/ (1):**
- `test_05_conversion.py` :: `test_activate_lease_on_non_vacant_lot_after_freeze_cycle_rejected` — removed incoherent setup that served an eviction on an already-FROZEN lot (rejected by PRD-faithful "serving a notice requires the lot OCCUPIED", §3.7). Now activates a lease directly against the frozen lot, cleanly exercising §3.2 ERR_LOT_FROZEN/ERR_LOT_NOT_VACANT.

**Fixes applied to implementation/ (1):**
- `app.py` :: `create_eviction_case` — eviction case `created_at`/`updated_at` now snapshot the logical clock (`server_now()`) instead of wall time. Per PRD §2.9 the notice is served at the logical instant, and §3.7 derives `cure_deadline` from the date portion of `created_at`. Wall-clock bug pushed cure deadlines ~5 months out, breaking TX cure-deadline derivation, both adjudication-cascade tests, and the cure-expired-beats-arrears precedence test. This single fix resolved 6 of 8 original failures.

## Step 8: Finalize PRD — 2026-05-30

PRD_FINALIZED.md produced (266 lines; 3 lines revised in place, 0% line-count delta, content expanded within existing lines).

Changes (3):
- §2.5 — revise — pinned `occupied_lot_count` as purely derived = current count of OCCUPIED-status lots (EVICTING/FROZEN/VACANT not counted), falls at notice-served/freeze/vacate — services.py:12-17, serialize.py:34.
- §3.3 — revise — pinned supersede-activation error precedence: PENDING first, then combined OCCUPIED + supersedes_lease_id==current_lease_id + prior-lease-ACTIVE (ERR_INVALID_STATE), preceding eviction-in-progress (ERR_EVICTION_IN_PROGRESS), preceding version check (ERR_STALE_LOT_VERSION) — app.py:322,355-375.
- §3.7 — insert — pinned eviction case `created_at` stamped from server logical instant (§2.9) not wall clock, so cure_deadline derivation tracks the test-driving clock; scoped to `created_at` only (post-creation touch() uses wall clock) — app.py:797-804.

NO-NEW-MISMATCH pre-edit searches logged for all 3 edits; wording widened/scoped to stay consistent with freeze cascade, first-occupancy path, and wall-clock updated_at on later transitions.

## Step 9: Complete PRD scan — 2026-05-30

PRD_COMPLETED.md produced. PRD_FINALIZED.md (266 lines, 35,916 chars) → PRD_COMPLETED.md (266 lines, 37,926 chars; +2,010 chars; all edits in-paragraph). **11 ambiguity-pins, 1 mismatch-revision** (12 changed paragraphs).

- §2.1 — revise — mismatch — X-User-ID stated "mandatory" but impl only gates X-User-Role; missing X-User-ID not rejected at auth — middleware.py:16-19
- §2.4 — insert — ambiguity — version starts at 1 on creation — db.py:61,79
- §2.5 — insert — ambiguity — multiple EFFECTIVE schedules: current_rent_cents uses latest effective_date, creation-order tiebreak — services.py:27-34
- §2.6 — insert — ambiguity — FK id resolution (404/400) runs before non-identifier body-field validation — app.py:232-245,255-263
- §3.3 — insert — ambiguity — expected_lot_version from lease-at-creation or activation body, body takes precedence — app.py:315,370-372
- §3.4 — insert — ambiguity — first application skips 12-month check; boundary one calendar year after prior, Feb 29→Mar 1, "on or after" — app.py:514-526,534-546
- §3.6 — insert — ambiguity — payment amount_cents positive int ≥1 else ERR_INVALID_REQUEST; ledger stores negation — app.py:395,400
- §3.8 — insert — ambiguity — eligible_lot_count zero at creation, snapshot to occupied_lot_count at open — app.py:931,963
- §3.8 — insert — ambiguity — eligible lot OCCUPIED or FROZEN; cross-community ballot lot → ERR_CROSS_COMMUNITY_REFERENCE; casting bumps vote version — app.py:984-994,1005
- §3.8 — insert — ambiguity — eligible_lot_count zero yields FAILED, not divide-by-zero — app.py:1048
- §4 — insert — ambiguity — posting payment returns 201 with new LotLedgerEntry — app.py:400,408

## Pipeline complete — all 9 steps done. Final 8-round sweep: 65/65 all rounds, 0 failures.

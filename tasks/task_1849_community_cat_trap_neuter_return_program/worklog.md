# Worklog — task_1849_community_cat_trap_neuter_return_program

## Step 1: Create Task Directory — 2026-08-14T20:41:05.560Z

Task directory `tasks/task_1849_community_cat_trap_neuter_return_program/` and `workspace/` pre-created by the pipeline invoker (Step 1 done externally; verified by orchestrator).

## Step 3: Copy Shared Files — 2026-08-14T20:41:22.398Z

Copied `./INSTRUCTION.md` to `tasks/task_1849_community_cat_trap_neuter_return_program/workspace/INSTRUCTION.md` (done ahead of Step 4 while Step 2 subagent runs — no dependency between them).

## Step 2: Generate Scaffold — 2026-08-14T20:59:35.551Z

## Summary

Generated a fresh scaffold for task 1849 (municipal TNR program) at `/home/ubuntu/github/CodingPRD/tasks/task_1849_community_cat_trap_neuter_return_program/` with three files:

**Counts**
- Entities: 13 (Caretaker, Colony, Cat, PartnerClinic, ClinicDay, ClinicSlot, TrappingAppointment, SurgeryRecord, Voucher, Complaint, FosterHome, FosterPlacement, PopulationSurvey — the last with `common_fields: false` for an immutability probe)
- State machines: 7 (Cat with branching + foster-loop cycle + adoption fall-through; TrappingAppointment; ClinicSlot; Voucher with ISSUED↔COMMITTED cycle; Complaint with severity-gated escalation; ClinicDay with close/no-show sweep; FosterPlacement)
- Calculations: 5 (colony_sterilization_rate with resident-basis variant; voucher_reimbursement_amount with municipal/donation variants; clinic_day_effective_capacity with kitten-season surge branch; voucher_monthly_issuance_cap waterfall with dead-voucher exclusion variant; population_trend_delta chronological with zero-baseline special case)
- Validations: 18 (ordered, spanning auth → existence → state → OCC → safety → referential → constraint → temporal → fiscal)
- Endpoints: 51 (including `POST /_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z default, and reverse-reachability GETs for every FK)
- Errors: 18
- Roles: 5 (peer_roles model — ProgramCoordinator, entity-backed Caretaker, ClinicStaff, AnimalControlOfficer, entity-backed FosterVolunteer; deliberately NOT hierarchical: coordinators cannot record surgeries)
- Difficulty instances: 18 (2 per rule × 9 rules, all differentiated per §0.5 clauses)
- Corner instances: 48 (43 with full test recipes across all nine claim-extraction-guide sections + 5 excluded-because stubs)

**Design decisions of note**
- Archetype: quota/allocation (clinic-slot capacity + voucher fiscal envelope) with workflow orchestration secondary; hybrid topology with cross-aggregate FKs.
- Two OCC concurrency rules: `appointment-create-stale-slot-day` (on ClinicDay.version) and `pathway-decide-stale-cat` (on Cat.version); every OCC payload in both design files references a `${var}` captured from a GET probe.
- Rounding order pinned: donation reimbursement computes `floor(min(face, cap) × 0.80)` — cap-before-floor — with literal expected values (20000/5000 split on face 25001, cap 25000).
- Kitten-season surge capacity is reachable only by kittens in months 3–7; adults are capped at base even when surge slots sit open (boundary instance uses base=1/surge=1).
- Voucher TTL uses calendar-month arithmetic (M+3), tested against the 2026-08-31 month-edge.
- `monitoring_status` is a compound posture: STABLE requires sterilized_pct ≥ 0.75 AND zero OPEN complaints (IN_MEDIATION doesn't block).
- No-show close sweep consumes the slot (USED) but releases the voucher (ISSUED) — an intentional asymmetry probed by the cascade instance.

**Verification**: `scaffold_lint.py` verdict — "clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5" (574 calls scanned). Also manually replayed and fixed three chain-level hazards the linter can't catch: booking a terminal RELEASED slot in the referential-vs-fiscal setup, an April 2026 clinic day in the past relative to the default logical clock (moved to April 2027, still in kitten season), and two future-dated population surveys (moved to 2026-08-01).

## Step 4: Generate PRD — 2026-08-14T21:13:07.678Z

PRD generation complete. Output: `/home/ubuntu/github/CodingPRD/tasks/task_1849_community_cat_trap_neuter_return_program/workspace/PRD.md` (289 lines). The two forbidden index files were never opened.

## Section structure

- **§1 Introduction** — 2 paragraphs, approached from municipal pain points (double-booked clinic days, lapsed vouchers, unquantified colony progress) and the deliberate authority partitioning across five roles.
- **§2 Global Specifications** — 11 subsections: 2.1 Roles & identity semantics (all 5 roles named; `Caretaker`→entity-backed `Caretaker.id`, `FosterVolunteer`→entity-backed `FosterHome.id`, the other three opaque); 2.2 verbatim response-envelope block (byte-identical, verified by diff); 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending); 2.4 Logical clock (2026-08-01T00:00:00Z default, `to_iso8601`, all server-stamped fields, date-only `service_date`); 2.5 Common resource properties (incl. the `PopulationSurvey` exception — no `updated_at`/`version`); 2.6 Sterilization rate & monitoring posture; 2.7 Clinic day capacity & kitten-season surge; 2.8 Voucher funding, monthly cap, reimbursement; 2.9 OCC; 2.10 Nested retrieval & validation order; 2.11 Population trend classification.
- **§3 Business Logic** — 9 lifecycle-grouped subsections (onboarding → clinic days → appointments → surgery → pathway/return-to-field → foster/adoption → complaints → vouchers → surveys/dissolution).
- **§4 Endpoint table** — 51 rows, 4 columns. **§5 Error catalogue** — 18 rows, 2 columns.

## Scaffold-to-prose mapping

- **Entities (13)**: all 55 field names woven into narrative; defaults stated inline (`certified_tnr` false, `accepts_vouchers` true, `surge_capacity` 0, `complications` false, `notes` empty, `voucher_id`/`pathway` null); derived fields (`is_kitten`, `sterilized_pct`, `monitoring_status`, `booked_count`, `current_kittens`, `severity`, `slot_index`, `issued_month`) explained at their natural homes.
- **State machines (7 machines, 32 transitions)**: every from→to pair rendered as state-pair prose (`AT_LARGE` → `TRAPPED`, `OPEN` → `IN_MEDIATION` → `RESOLVED`, etc.), including the foster loop, adoption fall-through, and no-show sweep; every precondition paired with its error; every cascade enumerated (surgery branches list cat fields + appointment + slot + `booked_count` + voucher + colony recompute).
- **Calculations (5)**: sterilization fraction (resident-set enumeration, 0.75 threshold, 4-dp half-up), voucher reimbursement (min-cap base, municipal full vs donation 80%-floor split), effective capacity (March–July kitten window, strict less-than, adult/surge boundary), monthly issuance cap (30,000 cents, live-status envelope, VOIDED/EXPIRED headroom release), trend delta (pinned surveyed_on/created_at ordering, inclusive ±20% thresholds, zero-baseline special case).
- **Validations (18)**: global class order in §2.10 plus explicit per-endpoint priority chains for appointments, decide-pathway, and foster placement; every `applies_to` scope enumerated (e.g. `ERR_OWNERSHIP_MISMATCH` named at mark-trapped, cancel, voucher commit, graduate, return-to-program).
- **Concurrency rules (2)**: §2.9 names both endpoints, `expected_clinic_day_version`/`expected_cat_version`, stale-read framing (no "simultaneous" language), `ERR_STALE_VERSION` + HTTP 412; states no other endpoint takes a version field.

## Scattering techniques

Constants embedded with unit/context conversion ("30,000 cents — three hundred dollars", "March through July", "younger than six months", "80 percent", "at least three months"); appointment-create parameters split across §3.3 (`cat_id`/`clinic_slot_id`/`trap_date`/OCC) and §3.8 (`voucher_id` usability); surgery record fields split between §3.4 (capture) and §3.5 (release-readiness reuse of `ear_tipped`/`vaccinated_rabies`); complaint severity derivation in §3.7 feeding the `STABLE`/`WATCH` rule back in §2.6.

## Self-check results

```
Field coverage check:
- entities[].fields: 55 required, 55 present, 0 missing
- endpoints[].request_body/input: 46 required, 46 present, 0 missing
- endpoints[].query_params: 5 required, 5 present, 0 missing
- path_params: 1 (id), present; common fields 4/4
Status: PASS

Rule coverage check:
- validations[] with priority: 18 checked, 18 expressed (global order + 3 endpoint chains)
- concurrency_rules[] OCC: 2 checked, 2 expressed (endpoint + expected_*_version + error_id + 412)
- state_machines[].transitions: 32 checked, 32 fully expressed
- calculations[]: 5 checked, 5 fully expressed (constants + precision in prose)
- validations[] conditions: 18 checked, 18 matchable to error_id in §2/§3 prose
- endpoints[].side_effects / applies_to: all expressed (51 endpoint rows, all side effects narrated)
- entities[].fields[] structured content: defaults/initials/derived all reconstructible
- sibling-branch symmetry: surgery outcomes, foster endings, funding variants, trend labels all symmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 325
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS

Auxiliary: §2.2 verbatim diff PASS; 29 state values, 5 roles, all enum values present; no pseudocode operators or fuzzy hedging words detected.
```

One checker caveat worth noting: naive backtick-pair extraction initially false-failed Contract 1 because the §2.2 JSON fences shift pairing; the checker strips fenced blocks before extraction, after which all 107 required identifiers confirmed present.

## Step 5: Generate Unit Tests — 2026-08-14T21:34:30.000Z

## Summary

**Generated** for `tasks/task_1849_community_cat_trap_neuter_return_program/`:

### test_helpers/ (9 files, 1247 lines)
- `types.py` — 13 entity TypedDicts + 18 enums; `PopulationSurvey` correctly omits `updated_at`/`version` (append-only per PRD §2.5), all others carry the four common fields.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (clock, caretakers, colonies, cats, clinics, clinic days/slots, appointments, surgery records, vouchers, complaints, foster homes/placements, surveys, population report).
- `api_errors.py` — `ApiErrorId` enum + full 18-error HTTP map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity `assert_*` using `is_valid_uuid`/`is_iso8601_timestamp`.
- `factories.py` — input-only payload factories with unique sequencing.
- `constants.py` — PRD thresholds (0.75 stable, kitten season 3–7, kitten age 6, 30000-cent cap, 0.80 donation share, 3-month TTL, ±0.20 trend).
- `test_users.py` — `TEST_USERS` constants for opaque roles + mandatory per-instance builders `make_caretaker_headers` / `make_volunteer_headers` for the two entity-backed roles.
- `fixtures.py` — composite builders: `setup_caretaker_with_colony`, `setup_clinic_day_with_slots`, `book_appointment` (auto-fetches live `ClinicDay.version` for OCC), `drive_cat_to_post_surgery`, `setup_cat_at_post_surgery` / `_returned` / `_in_adoption_pipeline`, `setup_kitten_in_foster`. All ownership-gated calls thread entity-backed headers.

### test_suite/ (10 files + conftest, 76 tests)
test_01_onboarding (10), test_02_envelope_and_auth (6), test_03_clinic_day_capacity (6), test_04_appointments (16), test_05_surgery_and_cascade (8), test_06_pathway_and_foster (14), test_07_vouchers (5), test_08_complaints (3), test_09_population_monitoring (6), test_10_colony_sterilization (2).

### Queue translation results
- **Queue A (Difficulty): 16/18 translated (≥2 tests each), 2 skipped.**
  - SKIP `dual_variant_calc/voucher_reimbursement_municipal_vs_donation` and `combinatorial_formula/donation_reimbursement_rounding_order`: both assert literal `reimbursement_cents`/`caretaker_share_cents` values on the Voucher response, but the PRD never names those as Voucher fields (nor any endpoint exposing the split) — a PRD-only reader could settle reimbursement internally. Fails unique-derivability; no placeholders emitted.
- **Queue B (Corner): 43/43 non-stub instances translated; 5 `excluded_because:` stubs correctly not translated** (all cross-references resolve to real difficulty instances, which are covered).

### Self-check results (all green)
- Syntax: all 19 files compile.
- C4 audit: every one of the 76 tests carries exactly one `Design:` line; all tags resolve to real instances in the correct section/rule; no tags point at stubs.
- Coverage audit: no shortfalls apart from the 2 adjudicated skips.
- C1 verbatim audit: every quoted PRD citation survives a whitespace-normalized grep of PRD.md (1 elided quote found and fixed).
- Import check: `test_helpers` and all 10 test modules import cleanly.
- No `skip`/`skipif`/`xfail` markers; no scaffold references in generated code.

One adjudication note: `Corner/cross_cutting_layers/version_increments_on_every_mutation` was translated with dynamic version capture (before/after equality across a rejected mutation) rather than the recipe's literal `version == 1`, because the PRD specifies "increments by one on every mutation" but never pins the initial value.

(Orchestrator note: the Step 5 subagent ended its first turn after adjudication without writing files; it was resumed via SendMessage and completed generation in the resumed turn. Timestamp above is the completion time of the resumed turn.)

## Step 6: Generate Implementation — 2026-08-14T21:35:30.000Z

Implementation complete and verified. Summary follows.

## File structure

`tasks/task_1849_community_cat_trap_neuter_return_program/workspace/implementation/` (17 Python files, ~2050 lines total):

- `start.sh` — exec-launches `python3 app.py`; dependency install guarded by `python3 -c "import flask"` so per-test reboots are no-ops (boot-to-HTTP measured at ~600 ms).
- `app.py` — Flask entry point, blueprint registration, envelope-shaped 404/405/500 handlers, a process-wide RLock acquired per request (immediate consistency under threaded serving).
- `db.py` — empty-on-boot in-memory store (13 entity dicts) + logical clock (default exactly `2026-08-01T00:00:00Z`, never wall-clock) + insertion sequence. **No seeding anywhere.**
- `errors.py` — all 18 catalog error IDs + `ERR_VALIDATION` (400) for missing/malformed fields (corner design pins "400 or 422" for those).
- `response.py` — envelope: `meta{api_request_id, api_request_timestamp}` (wall clock, matching the proven sibling task_1800 convention), `response_type`, `data`; list meta adds `limit/offset/total_count/has_more`; `limit` default 10 clamped to [1,100], `offset` default 0; lists sorted `created_at` ASC with insertion-order tie-break.
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401 `ERR_UNAUTHENTICATED` for missing/unknown role), per-endpoint role lists (403 `ERR_FORBIDDEN`), auth before lookup.
- `util.py` — ISO8601 parse/format (3-fractional-digit `Z`), typed field readers, `stamp_common` (version starts at 1), `touch` (version+1, updated_at refresh), PopulationSurvey stamped with id+created_at only.
- `routes/`: clock, caretakers, colonies (colonies + nested cats/complaints/surveys/report + dissolve), cats (decide-pathway/finalize-adoption/confirm-long-term + reverse lists), clinics (partner clinics/days/slots/close/cancel), appointments, surgery, vouchers, complaints, foster.
- `services/`: `colony_service` (sterilized_pct, 4dp ROUND_HALF_UP via Decimal; monitoring_status STABLE/WATCH/ACTIVE with 0.75 threshold on Decimal comparison; recompute always bumps colony version), `voucher_service` (30 000-cent monthly cap over ISSUED/COMMITTED/REDEEMED; municipal full vs donation `floor(base*0.80)` split in integer cents; 3-calendar-month expiry), `capacity_service` (kitten-season months 3–7, strict `<` on pre-increment booked_count), `trend_service` (Fraction-exact ±0.20 inclusive thresholds, surveyed_on/created_at-pinned ordering, zero-baseline GROWING/FLAT).

## Endpoints

All 51 routes from the endpoint table (52 Flask rules including static).

## Subsystem organization

- **State machines**: 7 machines, all transitions implemented — Cat (incl. foster loop POST_SURGERY↔IN_FOSTER and ADOPTION_PIPELINE→POST_SURGERY fall-through), TrappingAppointment (incl. NO_SHOW via close sweep), ClinicSlot (OPEN→BOOKED→USED/RELEASED), Voucher (ISSUED↔COMMITTED cycle, REDEEMED/VOIDED/EXPIRED), Complaint (severity-gated escalate; resolve is role×state paired — officer/IN_MEDIATION, coordinator/ESCALATED, else 409), ClinicDay (close sweep vs cancel), FosterPlacement.
- **Calculations**: the five scaffold calculations exactly as specified; `Voucher` exposes `reimbursement_cents`/`caretaker_share_cents` after redemption (pinned by difficulty asserts: 20000/0 municipal, 16000/4000 donation, 20000/5000 cap-before-floor).
- **Validations**: global order auth → authorization → existence (path left-to-right, then body FKs in declared order) → state (409) → OCC (412) → endpoint business rules per PRD §3 chains (booking: ownership → temporal → capacity → voucher-usable; foster: release-ready → kitten → home-full).
- **OCC**: `expected_clinic_day_version` on POST /tnr/appointments and `expected_cat_version` on decide-pathway; both non-optional (missing → 412); exact-match against parent version; every mutation (including cascades and colony recomputes) bumps version; failed requests mutate nothing.
- **Clock**: `POST /_clock/set_current_utc` (ProgramCoordinator) sets the logical clock; governs registered_on/filed_at/performed_at/placed_at/issued_month, created_at/updated_at, service_date past-check (calendar-date), trap_date strict precedence (instant vs service-day midnight), survey future-check (date), voucher TTL (calendar months).

## Self-check results

Two ad-hoc suites (135 assertions total) replaying the corner/difficulty design recipes — auth/envelope, uniqueness, kitten boundary, slot synthesis, OCC stale rejections on both guarded endpoints, surgery cascade with both reimbursement variants, WATCH↔STABLE flips on complaint status changes, foster loop + wrong-home 403, no-show sweep asymmetry (slot USED, voucher ISSUED, cat AT_LARGE, booked_count not decremented), capacity adult/kitten/season matrix, monthly-cap boundary (exactly 30000 admitted), mortality voiding freeing headroom, confirm-long-term qualifying survey, trend DECLINING/FLAT/GROWING incl. zero-baseline and same-day created_at tie-break, dissolve guard, all reverse-reachability lists — **all pass on fresh `bash start.sh` boots**.

## Two flagged ambiguities (decisions taken, for the record)

1. **decide-pathway check order**: PRD §3.5 and §2.10 order state (409) before OCC (412); the corner instance `decide_pathway_stale_cat_version` asserts 412 for a second call whose cat is already RETURNED (would be 409 under PRD order). I implemented the PRD order; the isolated stale case (cat POST_SURGERY + stale version) correctly returns 412. If the generated test asserts 412 for the combined state+stale scenario, flip the two checks in `routes/cats.py::decide_pathway`.
2. **Design-doc capture inconsistency** (not actionable): several recipes capture `$.data.version` from the POST /tnr/appointments response and reuse it as `expected_clinic_day_version`; the appointment's own version (1) can never equal the day version after booking+cascades, so these only work if the test generator re-probes via GET (as the worklog claims and as sibling task_1832's generated tests do). The implementation follows the PRD (day version bumps on every day mutation).

## Step 7: Run Tests and Iterate — 2026-08-14T21:52:00.000Z

All 8 rounds pass 76/76 — clean sweep. Exiting with the summary.

## Summary

**Iterations run:** 2 (initial sweep: 72/76 with 4 deterministic failures in all 8 rounds; post-fix sweep: 76/76 × 8 rounds, zero failures).

**Tests deleted:** None. All four failing tests asserted rules verbatim-covered and uniquely determined by PRD.md; all four were test-artifact bugs repaired in place.

**Fixes applied to `test_suite/`** (all four were test bugs; no `test_helpers/` or `implementation/` changes were needed — the implementation was PRD-faithful in every case):

1. `/home/ubuntu/github/CodingPRD/tasks/task_1849_community_cat_trap_neuter_return_program/test_suite/test_01_onboarding.py` — `test_colonies_list_pagination_envelope`: added the missing `create_colony` import (NameError). The asserted rule (PRD §2.3: "The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`") is verbatim-covered; the test body was already faithful.

2. `/home/ubuntu/github/CodingPRD/tasks/task_1849_community_cat_trap_neuter_return_program/test_suite/test_04_appointments.py` — `test_released_voucher_can_be_committed_again`: the test rebooked the released voucher onto `slots[0]`, which cancellation had moved `BOOKED → RELEASED` (PRD §3.3 verbatim), while booking requires an OPEN slot (PRD §3.3: "the slot must stand `OPEN` and its day still `SCHEDULED`, else `ERR_INVALID_STATE`"). Rebooked onto the day's still-OPEN `slots[1]`, preserving the PRD §3.8 assertion ("this issue-commit-release cycle may repeat any number of times").

3. `/home/ubuntu/github/CodingPRD/tasks/task_1849_community_cat_trap_neuter_return_program/test_suite/test_06_pathway_and_foster.py` — `test_decide_pathway_stale_cat_version` (the flagged friction point): adjudicated in favor of the implementation. The original test issued the second decision against a RETURNED cat — both state-illegal and version-stale — and asserted 412, contradicting PRD §3.5's explicit ordering ("its checks run existence, then state, then the stale-version rejection (`ERR_STALE_VERSION`), then release-readiness"). Restructured to the scenario §2.9 actually describes ("another pathway decision has advanced the cat since the client's last read — re-opening the decision by resetting `pathway`"): POST_SURGERY → ADOPTION → fall-through RETURN_TO_FIELD → POST_SURGERY (pathway null, version advanced twice), then decide with the stale observed version → `ERR_STALE_VERSION` (412). The exact-error assertion was kept, not relaxed.

4. `/home/ubuntu/github/CodingPRD/tasks/task_1849_community_cat_trap_neuter_return_program/test_suite/test_07_vouchers.py` — `test_voucher_not_expired_two_months_on`: a 2-month-old voucher is not expirable, so per PRD §3.8 verbatim ("If the sweep finds nothing old enough to expire, it is rejected with `ERR_NOTHING_TO_EXPIRE` (HTTP 422)") the sweep must 422; the test wrongly expected success. Changed to assert `ERR_NOTHING_TO_EXPIRE` (422) from the sweep and that the voucher remains `ISSUED` (rejected sweep mutates nothing), preserving the 2-months-vs-3-months boundary intent.

**Fixes applied to `implementation/`:** None — the implementation's behavior was PRD-faithful in all four failures.

## Step 8: Finalize PRD — 2026-08-14T21:53:38.480Z

All verification is complete. The conclusion is that **zero edits are warranted** — PRD_FINALIZED.md stands as a byte-identical copy of PRD.md (already placed by the initial `cp`).

## Summary

**Line counts / delta:** PRD.md = 288 lines; PRD_FINALIZED.md = 288 lines; 0% delta (byte-identical, confirmed by `diff`).

**Changes:** None. Every one of the four `<step_7_diff>` items was a test-artifact repair against a rule the PRD already pins verbatim, with the implementation PRD-faithful — so the minimal patch is the identity patch. The hard scope forbids any edit not traceable to a PRD-silence or PRD-mismatch revealed by those items, and none was found.

**Per-item pre-edit search log** (each candidate edit was rejected as unnecessary after enumerating the impl paths):

1. **§2.3 pagination envelope** (test_01 NameError fix)
   - (a) Subject: the four pagination fields in list-response `meta`.
   - (b) Paths enumerated: `implementation/response.py:34-41` (`success_array` writes exactly `limit`/`offset`/`total_count`/`has_more`), `response.py:73-78` (`paginate`), and all list callsites — `routes/colonies.py:83,148,183,227`, `routes/cats.py:164,175`, `routes/appointments.py:236,245`, `routes/clinics.py:143`, `routes/foster.py`, `routes/caretakers.py`, plus `routes/vouchers.py:77` (expire-sweep's direct `success_array`). All carry the four fields, matching §2.3's verbatim sentence.
   - (c) No wording change; rule already uniquely determined. No edit.

2. **§3.3/§3.8 released-voucher recommit** (test_04 rebook target fix)
   - (a) Subject: cancellation side effects and the booking state gate.
   - (b) Paths enumerated: `routes/appointments.py:196-225` (cancel: slot `BOOKED→RELEASED`, `booked_count−1`, voucher `COMMITTED→ISSUED`), `appointments.py:69-75` (booking requires slot `OPEN` and day `SCHEDULED`, else `ERR_INVALID_STATE`), `appointments.py:106-114` (voucher must stand `ISSUED`), and the parallel slot-release paths in `routes/clinics.py:152-206` (close-day sweep and day-cancel release `OPEN→RELEASED`; sweep releases voucher `COMMITTED→ISSUED`). All consistent with §3.3's "the slot must stand `OPEN`" and §3.8's "this issue-commit-release cycle may repeat any number of times", both verbatim in the PRD.
   - (c) No wording change; the cycle-repeat and OPEN-slot rules are already pinned. No edit.

3. **§3.5/§2.9 decide-pathway ordering and fall-through** (test_06 restructure, the flagged friction point)
   - (a) Subject: check order (existence → state → stale-version → release-readiness) and the ADOPTION_PIPELINE fall-through re-opening the decision.
   - (b) Paths enumerated: `routes/cats.py:39-106` — `get_cat_or_404` (existence, line 42), state legality (lines 55-68, including the kitten-ADOPTION and fall-through-only-RETURN_TO_FIELD branches), OCC (lines 71-75, `expected_cat_version` non-optional, 412), release-readiness (lines 79-82, applies to *any* pathway decision including fall-through), and the fall-through mutation (lines 98-100: `POST_SURGERY`, `pathway=None`) with `touch(cat)` at line 102 incrementing `version` (`util.py:78-80`). Every element is verbatim-pinned: §3.5 "its checks run existence, then state, then the stale-version rejection (`ERR_STALE_VERSION`), then release-readiness", "resets its `pathway` to null, re-opening the decision", "The decision itself is a mutation: it increments the cat's `version`", and §2.9's stale-read scenario. Step 7 adjudicated in favor of the implementation; the PRD text was the authority the fixed test now follows.
   - (c) No wording change; ordering and fall-through semantics already uniquely determined. No edit.

4. **§3.8 empty expiry sweep** (test_07 expectation fix)
   - (a) Subject: `ERR_NOTHING_TO_EXPIRE` (422) when no `ISSUED` voucher is ≥3 months old, and non-mutation on rejection.
   - (b) Paths enumerated: `routes/vouchers.py:66-78` (`expire_sweep` raises before any mutation; the 2-month-old voucher stays `ISSUED`), `services/voucher_service.py:64-66` (`expirable_vouchers`: `ISSUED` and whole-calendar-month diff ≥ 3 via `month_diff`, lines 33-38), and `errors.py` for the catalogue entry. Matches §3.8 verbatim: "If the sweep finds nothing old enough to expire, it is rejected with `ERR_NOTHING_TO_EXPIRE` (HTTP 422)"; "rejected" carries the PRD-wide no-mutation semantics used by every validation rule.
   - (c) No wording change; threshold, error, and rejection semantics already pinned. No edit.

**Deliverable:** `/home/ubuntu/github/CodingPRD/tasks/task_1849_community_cat_trap_neuter_return_program/workspace/PRD_FINALIZED.md` — identical to PRD.md. A fresh implementer reading it produces the current implementation, since the implementation was confirmed PRD-faithful in all four Step 7 cases and no PRD-silence or PRD-mismatch was revealed.

## Step 9: Complete PRD — 2026-08-14T22:04:19.837Z

PRD_COMPLETED.md is complete and verified. Final summary:

## Summary

**Source**: `PRD_FINALIZED.md` (288 lines, 41,646 chars) → `PRD_COMPLETED.md` (290 lines, 44,821 chars); char-delta **+3,151**; 44 changed/added diff lines.

**Counts**: 19 ambiguity-pins, 1 mismatch-revision (20 edits total).

### Changes

- **§2.1** — insert — ambiguity — Ownership checks apply only where §3 states one; list/fetch endpoints grant access by role alone (e.g., any Caretaker may fetch any caretaker/voucher, any FosterVolunteer any home) — implementation/routes/caretakers.py:38-44, vouchers.py:57-63, foster.py:61-75
- **§2.2** — insert — ambiguity — Request-level field failures (missing/mis-typed/out-of-range/non-enumerated/unparseable) rejected with `ERR_VALIDATION` (HTTP 400) in the standard envelope — implementation/errors.py:29,51; util.py:99-163
- **§2.3** — insert — ambiguity — Out-of-range `limit`/`offset` clamped into range, non-integer values fall back to defaults — implementation/response.py:50-70
- **§2.3** — insert — ambiguity — `created_at` ties broken by creation sequence, earlier-created first — implementation/util.py:83-86
- **§2.3** — insert — ambiguity — `total_count` counts the filtered set pre-pagination; `has_more` ⟺ `offset` + returned items < `total_count` — implementation/response.py:34-41,73-78
- **§2.4** — insert — ambiguity — Clock accepts any instant (earlier or later); logical clock governs entity stamps only, envelope `api_request_timestamp` is wall-clock; date/datetime inputs accept date-only forms, naive values read as UTC, submitted strings stored and returned verbatim (`service_date`, `trap_date`, `surveyed_on`) — implementation/routes/clock_routes.py:13-18; response.py:20-26; util.py:39-55; routes/colonies.py:212
- **§2.5** — insert — ambiguity — `updated_at` initialized equal to `created_at`; `version` starts at 1 on creation — implementation/util.py:58-66
- **§2.7** — insert — ambiguity — Kitten season judged by the month of the hosting clinic day's `service_date` (not the booking-time clock) — implementation/services/capacity_service.py:14-19
- **§2.8** — insert — ambiguity — Voucher carries `reimbursement_cents` and `caretaker_share_cents`, both null from issuance until redemption records the split — implementation/routes/vouchers.py:50-51; services/voucher_service.py:52-61
- **§2.9** — insert — ambiguity — Omitting `expected_clinic_day_version`/`expected_cat_version` is treated as a version mismatch → `ERR_STALE_VERSION` (412) — implementation/routes/cats.py:71-75; appointments.py:78-82
- **§3.1** — insert — ambiguity — No ownership check at cat intake; a caretaker may add cats to any colony — implementation/routes/colonies.py:107-136
- **§3.1** — insert — ambiguity — `caretaker_id` and `monitoring_status` colony-list filters combine conjunctively — implementation/routes/colonies.py:75-83
- **§3.2** — insert — ambiguity — Clinic-day slot list is ordered by `slot_index` ascending (the §2.3 "otherwise specified" case) — implementation/routes/clinics.py:142
- **§3.3** — revise — **mismatch** — PRD said the `status` filter extended to slot/voucher appointment lists ("as are..."); impl supports it only on a cat's appointment history, so prose revised to "listable without one" for the slot and voucher lists — implementation/routes/appointments.py:156-164 vs 230-245
- **§3.3** — insert — ambiguity — Check-in response carries the (unchanged) appointment object — implementation/routes/appointments.py:189-193
- **§3.5** — insert — ambiguity — A `pathway` value outside `RETURN_TO_FIELD`/`ADOPTION` is rejected at the state step with `ERR_INVALID_STATE` (not a field-validation error) — implementation/routes/cats.py:44-49
- **§3.6** — insert — ambiguity — On graduate/return-to-program, state checks (cat `IN_FOSTER`, then placement `ACTIVE`) precede the ownership check — implementation/routes/foster.py:130-142
- **§3.8** — insert — ambiguity — Expire-sweep success responds 200 with a list envelope carrying exactly the expired vouchers, unpaginated — implementation/routes/vouchers.py:66-78
- **§3.9** — insert — ambiguity — Survey future-check compares `surveyed_on` as a calendar date; a survey dated the current logical day is admitted — implementation/routes/colonies.py:204-208
- **§3.9** — insert — ambiguity — Population report field shape pinned: `colony_id`, `survey_count`, `first_observed_count`, `last_observed_count`, `delta_pct`, `trend`; counts and `delta_pct` null under `INSUFFICIENT_DATA`; `delta_pct` carries the unrounded ratio except zero-baseline (null when grew, 0 when flat) — implementation/services/trend_service.py:26-58
- **§3.9** — insert — ambiguity — Dissolution requires the colony to still stand `REGISTERED` (re-dissolve → `ERR_INVALID_STATE`, checked before the terminal-resident rule); dissolution does not block later cat intake, complaint filing, or survey recording — implementation/routes/colonies.py:86-102,107-136
- **§5** — insert — ambiguity — Added catalogue row `ERR_VALIDATION | 400 Bad Request` — implementation/errors.py:29

Notable verified non-changes (PRD already uniquely pins impl): booking's eight-step check order, foster-placement check order, complaint transition/role matrix, capacity strict-less-than semantics, monthly-cap exact-landing admission, reimbursement floor arithmetic, trend thresholds/zero-baseline, sweep not decrementing `booked_count`, and the mark-trapped recompute-without-numeric-change.

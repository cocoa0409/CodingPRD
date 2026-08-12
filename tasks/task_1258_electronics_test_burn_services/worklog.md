# Worklog — task_1258_electronics_test_burn_services

Scenario: 1258. Electronics Test & Burn-In Services (third-party test house): test program & fixture development, chamber slot scheduling & profile, serialized pass/fail & bin mapping, retest policy & escape analysis, customer-owned equipment maintenance, yield reporting & lot disposition, ESD program audit, RMA failure analysis loop

Difficulty parameter: "generate task hard than expert level!"

## Step 1: Create Task Directory — 2026-08-12T00:00:00.000Z

Pre-assigned output folder `tasks/task_1258_electronics_test_burn_services` with `workspace/` subdirectory already exists. Step 1 auto-index scan skipped per instructions; treating Step 1 as done.

## Step 2: Generate Scaffold — 2026-08-12T11:14:00.000Z

All three scaffold artifacts are generated and lint-clean.

## Deliverables (all under `/home/ubuntu/github/CodingPRD/tasks/task_1258_electronics_test_burn_services/`)

- **SCAFFOLD.yaml** — §1.0–§1.7 only (no difficulty/corner keys): 14 entities, 13 state machines, 10 calculation rules, 36 ordered validation rows, 70 endpoints, 34 error codes, 4 roles, 2 OCC concurrency rules. Fixed response envelope verbatim. Logical clock endpoint (`POST /api/_clock/set_current_utc`) with the mandatory `2026-05-01T00:00:00Z` startup default stated in its description.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — `scaffold_difficulty_design:` with all 9 rules × 2 instances = 18 instances, each with structured `setup_api_calls`/`trigger` chains and literal-computed asserts.
- **SCAFFOLD_CORNER_DESIGN.yaml** — `scaffold_corner_design:` across all 9 guide sections: 51 active instances + 17 `excluded_because:` stubs (all stub refs resolve to difficulty instances). 86 instance names unique across both files.

## Design (beyond-Expert calibration)

- **Profile**: primary `temporal_windowing` (chamber slots), secondary `event_sourcing` (unit state = replay of non-voided TestResults); layers: OCC, cascading side effects, dual-variant calc, threshold triggers. Graph topology with self-referential (`TestProgram.supersedes_program_id`) and polymorphic (`MaintenanceOrder.target_id`) FKs; `segregation_of_duties` role model (retest authorizer ≠ failing-result recorder, QE-only voids/dispositions).
- **Rule differentiation highlights**: dual-variant calcs on Lot yield (FIRST_PASS 0.5 vs FINAL 0.75) vs Chamber utilization (SCHEDULED 0.15 vs ACTUAL 0.2); combinatorial modes (a) 3-input nested disposition branching vs (b) pinned per-segment-then-sum rounding (92 ≠ 93); cascades depth-3 (program release → obsolete → fixture decommission → reservation cancel → slot ledger) vs depth-2 (RMA close → lot containment → auto MRB review); priority conflicts on (business_safety, business_temporal) and (state, business_referential); boundaries on retest-count strict-`<` vs FPY inclusive-`>=` (0.75 ships, 0.5 rejected); overlap semantics half-open+class-conditional purge buffer (Chamber) vs closed-interval touching-conflict (Equipment); compensating invariants on chamber slot ledger (Σ+available == 8) and lot unit census (== quantity).
- **Constraint honored**: no sibling task directories were read; the design was built purely from the scenario text plus the skill spec.

## Verification

- `scaffold_lint.py` verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (70 endpoints, 14 entities, 18 + 51 instances, 847 calls scanned, 0 violations)
- Additional sweeps: all 34 error codes referenced by validations/transitions; all endpoint roles ∈ RBAC; all `grounds:` refs resolve; no forbidden concurrency vocabulary; every setup chain replayed call-by-call against §1.2/§1.4 (caught and fixed one real defect during replay: direct-ship dual-gate shadowing between `ERR_REVIEW_PENDING` and `ERR_DISPOSITION_REVIEW_REQUIRED`, resolved by scoping the former to review creation only).

Note: the task directory already contained `worklog.md` and `workspace/` (predating this run); per the hard constraint I did not read them.

## Step 3: Copy Shared Files — 2026-08-12T11:15:00.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-12T11:30:00.000Z

The PRD is complete and verified. Final summary:

**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_1258_electronics_test_burn_services/workspace/PRD.md` — a prose PRD for the Electronics Test & Burn-In Services API, projected losslessly from `SCAFFOLD.yaml` (the difficulty/corner design files were not opened or referenced).

**Structure:** §1 introduction (2 paragraphs, business-context angle); §2 with 11 domain-derived subsections (roles/identity, verbatim response envelope, pagination, common resource properties including the TestResult `common_fields: false` exception, the logical clock with the `2026-05-01T00:00:00Z` startup default, OCC, precision/rounding, the chamber slot ledger, interval semantics with the 30-minute purge buffer and closed maintenance windows, ESD containment, and the nine-rung validation priority ladder); §3 with 9 lifecycle/workflow subsections carrying all scattered business logic with zero paths; §4 with a 70-row endpoint table (4 columns); §5 with a 34-row error catalogue (2 columns). No audit footer.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 70 required, 70 present, 0 missing
- endpoints[].request_body (+computed outputs): 11 required, 11 present, 0 missing
- endpoints[].query_params: 2 required (limit, offset), 2 present, 0 missing
- nested object members (burn_profile/findings/corrective_actions): 7 required, 7 present, 0 missing
- path params in §4: 14 required, 14 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] priority ladder: 9 rungs expressed in §2.11 with first-failure-wins semantics, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (revisions mint + reservation reschedule; occ_field, ERR_STALE_VERSION/412 named; no race framing), 0 missing
- state_machines[].transitions: all transitions across 13 machines expressed (supersession 4-hop cascade, fixture/chamber cascades, retest loop, REWORK reset, TEST_ESCAPE containment), 0 missing
- calculations[]: 9 checked, 9 fully expressed (dual-variant yields, top-down disposition thresholds 0.75/0.50/0.25/escape>=1 on exact fractions, per-segment round-half-up burn duration from 25 °C ambient, SCHEDULED vs ACTUAL utilization, slot ledger compensating pair, tally replay invariant, inclusive calibration boundary, ESD predicate, four-gate retest policy), 0 missing
- validations[] conditions: 30 checked, all matchable to their error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed, including full PATCH-reschedule re-validation scope (window, chamber-online, fixture-available, profile support, capacity, overlap, buffer, ESD, self-exclusion), 0 missing
- entities[].fields[] structured content: all defaults/initials stated (requires_esd_certification false, account_status ACTIVE, supersedes_program_id null, outcome/decision/rationale null, corrective_actions [], voided/excluded false, 48h expiry), 0 missing
- sibling-branch symmetry: FIRST_PASS/FINAL, SCHEDULED/ACTUAL, 4 disposition branches, AWAITING_DISPOSITION/CONTAINED decision matrix, PASS/PASS_WITH_MINOR/FAIL — equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 484
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional structural checks passed: §2.2 emitted byte-identical to `section-2.2-response-structure.md`; pagination defaults (limit 10, min 1, max 100, offset 0, `created_at` ascending) stated; all 34 error IDs and all state/enum values appear as exact backticked strings; both `TestEngineer`-opaque and `CustomerRep` entity-backed identity rules translated into §2.1 prose.

## Step 5: Generate Unit Tests — 2026-08-12T11:55:00.000Z

Done. Both stages are complete and fully audited.

## What was generated

**`/home/ubuntu/github/CodingPRD/tasks/task_1258_electronics_test_burn_services/test_helpers/`** (9 files):
- `types.py` — 13 entity TypedDicts + status/role enums; `TestResult` correctly carries only `id` + `created_at` (append-only, no `updated_at`/`version` per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (58 methods, all under `/api`)
- `api_errors.py` — all 34 error IDs with HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions, `assert_lot_tally_invariant`, `assert_chamber_slot_invariant`, `parse_iso8601` (instant comparison without pinning timestamp string format)
- `factories.py`, `constants.py` (SHIP_FPY 0.75 / RETEST_RATE_MAX 0.25 / SCRAP_FPY 0.50 / purge 30 min / auth TTL 48h / ambient 25 °C)
- `test_users.py` — shared constants for the three opaque roles + `make_customer_rep_headers(customer_id)` for the entity-backed CustomerRep role, threaded through all ownership-gated calls
- `fixtures.py` — composite setups: released-program scaffold, queued/IN_TEST/AWAITING_DISPOSITION/SHIPPED lot pipelines, reservation scenarios with clock positioning, retest authorization, RMA-in-FA, program revision minting and supersession

**`test_suite/`** — `conftest.py` + 10 test files, **88 tests**, all collected cleanly by pytest.

## Coverage audit (both mandatory passes run programmatically)

- Queue A: all 18 difficulty instances have ≥2 tests (36 tests), tagged `Design: Difficulty/<rule_id>/<name>`
- Queue B: all 50 non-stub corner instances have ≥1 test, tagged `Design: Corner/<section>/<name>`; all 15 `excluded_because:` stub cross-references resolve to real difficulty instances
- Zero orphan tags, zero tests with missing/duplicate tags, no `skip`/`skipif`/`xfail`
- All 150 quoted PRD citation segments survive literal grep of `PRD.md` (whitespace-normalized); no "scaffold" references in generated code

## Deliberate gap (1 instance skipped, not weakened)

**`Corner/validations/program_superseded_single_failure`** was skipped per the PRD-first two-condition filter. The instance asserts `ERR_PROGRAM_SUPERSEDED` in single-failure isolation, but that is unreachable: supersession cascade-decommissions every fixture of the old program (so any old-program fixture also triggers `ERR_FIXTURE_NOT_AVAILABLE`), and any other program's fixture also triggers `ERR_FIXTURE_PROGRAM_MISMATCH`. Both rival errors sit in the same priority rung (rung 8), and PRD §2.11 pins only cross-rung ordering ("the first failing rung determines the error returned"), not within-rung order — so two faithful PRD-only implementers can return different error IDs. Gap left as a gap.

One sub-assertion was also dropped for the same reason: `customer_creation_applies_defaults`'s `version == 1` check (PRD §2.4 says version "increments by one with every modification" but never states the initial value; the test still asserts the two PRD-covered defaults, `requires_esd_certification == false` and `account_status == ACTIVE`).

## Step 6: Generate Implementation — 2026-08-12T11:55:00.000Z

Implementation complete and verified. 

## What was built

A complete Python + Flask implementation of the Electronics Test & Burn-In Services API at `/home/ubuntu/github/CodingPRD/tasks/task_1258_electronics_test_burn_services/workspace/implementation/`:

- `start.sh` — executable, guarded pip install (no-op when Flask present, so per-test reboots don't contend), `exec python3 app.py` in foreground, binds `0.0.0.0:$PORT` (default 10000)
- `app.py` — Flask assembly, global RLock around requests, envelope-wrapped error handlers for ApiError/404/405/500
- `db.py` — in-memory store, empty at boot, logical clock defaulting to exactly `2026-05-01T00:00:00Z`
- `errors.py`, `envelope.py`, `auth.py`, `util.py` — error catalog (all 34 error IDs), `meta`/`response_type`/`data` envelope with `req_` IDs and 3-fractional-digit timestamps, `X-User-ID`/`X-User-Role` auth with the 4 roles, ISO-8601 parsing and second-precision timestamp comparison
- `services.py` — unit tally projection (replay of non-voided/non-excluded results), lot tallies/escape count derivation, exact-Fraction yield and disposition-suggestion thresholds, per-segment round-half-up burn duration (ambient 25 °C), slot ledger, half-open overlap + 30-min purge buffer, closed-interval maintenance conflicts, ESD containment predicate, whitelisted serializers
- `routes_core.py`, `routes_lots.py`, `routes_ops.py` — all 72 endpoints from SCAFFOLD §1.5

## Key fidelity decisions (PRD-verified)

- **Validation ladder order** per endpoint: auth → role/ownership → existence (path then body order) → state → OCC (412) → safety (suspension/ESD/segregation) → temporal → referential → constraints. E.g. enqueue checks program-RELEASED (422) before units-complete (409); reservation create checks ESD before window well-formedness, capacity before profile-support.
- **TestResult** carries only `id` + `created_at` (no `updated_at`/`version`); voided results stay immutable with history preserved (`retest_count` not decremented on void).
- **Lazy derivations**: `CALIBRATION_DUE` (inclusive boundary) and authorization `EXPIRED` computed at read/consume against the logical clock; wall clock never used except `api_request_timestamp`.
- **Supersession cascade** (release): prior RELEASED → OBSOLETE, its fixtures → DECOMMISSIONED, their RESERVED reservations → CANCELLED, each with version bumps; fixture-maintenance and chamber-offline cascades likewise.
- **RMA TEST_ESCAPE close**: unit force-failed (bin nulled), lot SHIPPED→CONTAINED, escape count derived from closed cases, suggestion recomputed to SCRAP_REVIEW, auto PENDING review. REWORK resets units and excludes results.
- Input-supplied datetimes echoed verbatim; computed datetimes formatted in the input's style; OCC fields `expected_test_program_version` / `expected_chamber_reservation_version` required and enforced.

## Verification

Booted via `bash start.sh` and ran ~100 behavioral checks across six smoke suites covering auth/envelope/404s, CRUD, all state machines, both OCC rules, retest segregation/expiry/limit, void replay, yield variants (0.75/1.0, 0.5 cases), MRB decide (SHIP/SCRAP/REWORK), ESD gate open/close, reservation windows/overlap/buffer/capacity boundaries, utilization SCHEDULED vs ACTUAL (including elapsed-window and negative-denominator cases), maintenance windows (touching-conflict, target lockout, calibration restamp), and pagination bounds — all pass. Fresh-boot check confirmed empty store and the exact default logical clock.

[Orchestrator note: route-parity check confirmed implementation registers exactly the 70 (method, path) pairs declared in SCAFFOLD.yaml §1.5 — 0 missing, 0 extra.]

## Step 7: Run Tests and Iterate — 2026-08-12T12:15:00.000Z

## Summary

- **Iterations run**: 2 (initial sweep: 85/88 in all 8 rounds, 3 deterministic failures, zero flakiness; post-fix sweep: **88/88 in all 8 rounds — clean exit**).

- **Tests deleted**: none. All three failing tests traced to PRD-verbatim rules with unique derivability; all three were test-side arithmetic/setup mis-translations, not coverage gaps.

- **Fixes applied to `test_suite/`** (all STEP 2 — assertion/setup mis-translates PRD; implementation was PRD-faithful in every case):
  1. `test_03_lots_and_units.py :: test_unit_registration_at_quantity_boundary` — the test called `create_lot_with_units(ctx, 1, ...)`, which creates a lot with `quantity=1` **and** registers 1 unit (lot already full), then wrongly expected a 2nd registration to return 201 with a comment claiming `quantity == 2`. PRD §3.4: "the registration that brings the count exactly to `quantity` is allowed, and any registration beyond that is rejected with `ERR_QUANTITY_EXCEEDED`" — the implementation's 422 was correct. Fixed the test to build a `quantity=2` empty lot, register Q-1 (below → 201), Q-2 (exactly → 201), Q-3 (beyond → 422 `ERR_QUANTITY_EXCEEDED`), covering all three boundary arms.
  2. `test_05_slot_ledger_and_utilization.py :: test_reserve_cancel_returns_ledger_to_prior_value` — asserted `available_slots == 5` after cancelling R1(3) with R2(5) still RESERVED on an 8-slot chamber; PRD §2.8's unconditional definition (`available_slots = slot_count − committed load`) uniquely yields 8−5=**3** (5 matched no PRD reading: pre-R1 value was 8, pre-cancel was 0). Fixed assertion to 3 with corrected comment (compensating cancel frees exactly R1's 3 slots: 0+3).
  3. `test_05_slot_ledger_and_utilization.py :: test_reserve_cancel_pair_statuses` — same mis-computation; its own comment was self-contradictory ("5 committed + 5 available == slot_count 8", i.e. 10==8). Fixed to `available_slots == 3` so conservation 5+3=8 holds.

- **Fixes applied to `test_helpers/`**: none needed — factories/fixtures behaved per their contracts; the bugs were in the test functions' use of them.

- **Fixes applied to `implementation/`**: none — the implementation was PRD-faithful on all three rules (quantity boundary, slot-ledger definition, compensating cancel).

[Orchestrator verification: all 8 results files on disk, each passed=88 total=88 failed=0.]

## Step 8: Finalize PRD — 2026-08-12T12:20:00.000Z

Done. `PRD_FINALIZED.md` is an exact copy of `PRD.md` — analysis showed zero edits were warranted.

## Summary

**Line counts:** PRD.md = 353 lines, PRD_FINALIZED.md = 353 lines, **0% delta** (`diff` confirms byte-identical).

**Changes:** none.

### Why no edits

All three `<step_7_diff>` items are test-side arithmetic/setup mis-translations where the PRD already uniquely determines behavior and the implementation is PRD-faithful. Per the method ("patch only when impl pinned a choice PRD left open, or impl mismatches PRD"), no patch applies:

- **Item 1 — quantity boundary (PRD §3.4):** Impl `create_unit` (`implementation/routes_lots.py:207-209`) rejects with `ERR_QUANTITY_EXCEEDED` (422) exactly when `len(lot_units(...)) >= quantity` — so the registration bringing the count exactly to `quantity` succeeds and any beyond fails, verbatim per §3.4. The deleted test expectation assumed a `quantity=1` lot could accept a 2nd unit; pure fixture bug.
- **Item 2 — reserve/cancel ledger value (PRD §2.8):** Impl `chamber_available_slots` (`implementation/services.py:165-173`) computes `slot_count − Σ slot_count over RESERVED/IN_PROGRESS`, recomputed lazily on every read via `ser_chamber` (`services.py:282`); cancel (`routes_core.py:609-616`) just flips status to `CANCELLED` via `cancel_reservation` (`services.py:176-178`). With R1(3) cancelled and R2(5) still RESERVED on an 8-slot chamber, §2.8's unconditional definition uniquely yields 8−5=3; the test's `==5` matched no PRD reading. Test bug.
- **Item 3 — pair-status conservation:** identical code path and PRD sentence as item 2; the test's own comment was arithmetically inconsistent (5+5≠8). Test bug.

### Pre-edit search log

No edits were committed, so the per-edit log is vacuous — but the path enumeration that justified the "no edit" verdict for each subject:

1. **Subject: unit quantity boundary.** Enumerated paths: `create_unit` (`routes_lots.py:190-215`, the sole mutator of unit count), `lot_tallies` (`services.py:101-114`, sole reader computing `units_registered`), and its consumers `ser_lot` (`services.py:297-312`), `enqueue_lot` (`routes_lots.py:109-112`). PRD §3.4's verbatim sentence correctly describes all of them → no edit.
2. **Subject: slot ledger / available_slots.** Enumerated paths: definition `chamber_available_slots` (`services.py:165-173`, includes `IN_PROGRESS` per PRD); call sites `ser_chamber` (read path, `services.py:282`) and capacity check `_reservation_business_checks` (`routes_core.py:482-485`, shared by create `routes_core.py:507` and reschedule `routes_core.py:568` with self-exclusion); all status-flip writers whose frees flow through the lazy recompute — cancel (`routes_core.py:615`), complete (`routes_core.py:604`), and the fixture-maintenance / chamber-offline / supersession cascades (`routes_core.py:251, 338, 403`). PRD §2.8's wording (definition + compensating-pair invariant + capacity bounds) is consistent with every enumerated path → no edit.

## Step 9: Complete PRD — 2026-08-12T12:35:00.000Z

All edits are verified in the diff. The task is complete.

## Summary

**Source vs output**: `PRD_FINALIZED.md` (353 lines, 58,552 chars) → `PRD_COMPLETED.md` (357 lines, 62,855 chars; **+4 lines, +4,303 chars**).

**Counts**: 22 ambiguity-pins, 5 mismatch-revisions (27 change points across 21 diff hunks; all in-paragraph edits, no new sections).

### Changes

**§2.3 Pagination** — insert — ambiguity — out-of-range/non-integer `limit`/`offset` rejected with `ERR_INVALID_REQUEST` — `implementation/routes_core.py:42-52`
**§2.3 Pagination** — insert — ambiguity — creation-timestamp ties broken by creation sequence — `implementation/services.py:45-46`
**§2.4 Common properties** — insert — ambiguity — `version` starts at 1 on creation — `implementation/services.py:28`
**§2.4 Common properties** — insert — ambiguity — `created_at`/`updated_at` stamped from the logical clock, never wall clock; client-supplied timestamps echoed verbatim — `implementation/services.py:19-21`, `implementation/routes_core.py:512`
**§2.5 Logical clock** — insert — ambiguity — clock-set response `current_utc` echoes the supplied `to_iso8601` string — `implementation/routes_core.py:85-86`
**§2.5 Lazy states** — insert — ambiguity — `status` list filters on equipment and authorizations match the effective (derived) status — `implementation/routes_ops.py:70-72`, `implementation/routes_lots.py:418-421`
**§2.8 Slot ledger** — insert — ambiguity — `slot_count` below 1 also rejected with `ERR_SLOT_CAPACITY_EXCEEDED` — `implementation/routes_core.py:483-485`
**§2.9 Windows** — revise — ambiguity — reschedule self-exclusion covers the purge-buffer scan as well as the overlap scan — `implementation/services.py:233-234`
**§2.11 Ladder rung 4** — revise — mismatch — `ERR_REVIEW_PENDING` gate applies to manual opens only; automatic creation exempt — `implementation/routes_lots.py:142-143`, `implementation/routes_ops.py:376`
**§2.11 Ladder rungs 7/9** — revise — mismatch — `ERR_AUTHORIZATION_EXPIRED` moved from rung 7 to rung 9, evaluated immediately after `ERR_NO_ACTIVE_AUTHORIZATION` (i.e., after bin-mapped and immutability checks) — `implementation/routes_lots.py:288-301`
**§2.11 Ladder** — insert — ambiguity — request-shape validation (`ERR_INVALID_REQUEST`) is not ladder-ordered (endpoint-specific); scope derived from a referenced lot requires the lot's existence first (`ERR_NOT_FOUND` before `ERR_FORBIDDEN_OWNERSHIP`), while lot creation checks body `customer_id` scope before existence — `implementation/routes_lots.py:57-59,197-200`, `implementation/routes_ops.py:293-297`
**§3.1 Customers** — revise — ambiguity — PATCH assigns values directly (re-assigning current value allowed) and every PATCH call increments `version` even on no-op — `implementation/routes_core.py:118-130`
**§3.2 Programs** — insert — ambiguity — `bin_map` non-empty with string keys; `max_retests_per_unit` integer ≥ 0; `burn_profile` may be empty (duration 0), segment fields numeric with `ramp_rate_c_per_min` > 0 and `soak_minutes` ≥ 0 — `implementation/routes_core.py:137-163,174`
**§3.2 Fixtures** — insert — ambiguity — `site_count` must be an integer ≥ 1 — `implementation/routes_core.py:292`
**§3.3 Chambers** — insert — ambiguity — a PATCH carrying no `status` change leaves the chamber and its `version` untouched — `implementation/routes_core.py:390-404`
**§3.3 Reservations** — revise — ambiguity — `profile_class` outside `A`/`B`/`C` is malformed (`ERR_INVALID_REQUEST`); `ERR_PROFILE_NOT_SUPPORTED` only for a well-formed class the chamber lacks — `implementation/routes_core.py:497,486-488`
**§3.3 Reschedule** — insert — ambiguity — `start_at`/`end_at`/`slot_count`/`profile_class` all optional and merged with current values; only `expected_chamber_reservation_version` mandatory — `implementation/routes_core.py:545-557`
**§3.3 Utilization** — insert — ambiguity — `window_start`/`window_end`/`basis` query params all required; slot-minute totals serialized as integers when whole, exact decimals otherwise — `implementation/routes_core.py:412-414,447-448`
**§3.5 Results** — insert — ambiguity — `bin_code` must be an integer; digit strings coerced, anything else `ERR_INVALID_REQUEST` — `implementation/routes_lots.py:249-254`
**§3.5 Tallies** — revise — mismatch — `units_untested`/`units_passed`/`units_failed` sum to `units_registered` (not `quantity`; equal only once the manifest is complete) — `implementation/services.py:101-114`
**§3.5 Retest consume** — insert — ambiguity — multiple `ACTIVE` authorizations may coexist; the earliest-created still-live one is consumed — `implementation/routes_lots.py:296-301`
**§3.5 Revocation** — insert — ambiguity — revocation is gated on effective status; a lazily-`EXPIRED` authorization cannot be revoked (`ERR_INVALID_STATE`) — `implementation/routes_lots.py:430-431`
**§3.5 Voiding** — insert — ambiguity — refusal order: lot not `SHIPPED` → not already voided → is latest tally-effective; void does not increment the unit's or lot's `version` — `implementation/routes_lots.py:356-365`
**§3.6 Reviews** — revise — mismatch — "only one PENDING review" scoped to manual opens; automatic creation (complete-test, RMA containment) performs no check, so a lot can hold several `PENDING` reviews — `implementation/routes_lots.py:33-40,142-143`, `implementation/routes_ops.py:376`
**§3.7 Maintenance** — insert — ambiguity — orders may be scheduled against a target in any status (even `RETURNED`/`OFFLINE`); target standing gated only at start — `implementation/routes_ops.py:103-106,161-162`
**§3.8 Audits** — revise — mismatch — findings entries require only `severity`; `description` optional — `implementation/routes_ops.py:220-223`
**§3.8 Audit close** — insert — ambiguity — `finding_index` is the zero-based position in `findings`; only its presence is validated — `implementation/routes_ops.py:259-265`

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1258_electronics_test_burn_services/workspace/PRD_COMPLETED.md`

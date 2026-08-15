# Worklog — task_1933_equine_rescue_sanctuary_operations

## Step 1: Create Task Directory — 2026-08-15T01:32:00.000Z

Directory `tasks/task_1933_equine_rescue_sanctuary_operations/` and `workspace/` pre-created by the pipeline invoker (per command args); index 1933 assigned externally. No bash action taken by orchestrator.

## Step 2: Generate Scaffold — 2026-08-15T02:14:07.806Z

All three scaffold artifacts are generated, lint-clean, and audit-clean. Final summary:

## Generated: task_1933_equine_rescue_sanctuary_operations

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1933_equine_rescue_sanctuary_operations/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — §1.8, single top-level `scaffold_difficulty_design:`
- `SCAFFOLD_CORNER_DESIGN.yaml` — §1.9, single top-level `scaffold_corner_design:`

**Counts**
- Entities: 22 (Horse with self-referential `bonded_companion_id`, append-only DailyHealthLog/FeedDayClose, CareServiceAppointment with parallel `status × billing_status` dimensions, etc.)
- State machines: 14 — cyclic Horse lifecycle (incl. ADOPTED→REHABILITATION return loop and END_OF_LIFE_REVIEW prior-status restore), cyclic AdoptionApplication home-check retry loop, cyclic Sponsorship ACTIVE↔LAPSED, compliance-chained EuthanasiaCase
- Calculations: 7 — incl. dual-variant lifetime care cost (ACTUARIAL vs STRAIGHT_LINE), dual-variant feed supply (TIGHT vs COMMITTED), QUOTED-vs-FINAL adoption fee, per-lot-then-sum PO rounding with pinned order, BCS-factored ration, chronological quarantine release timing, decay-based volunteer reliability
- Endpoints: 105 (incl. `POST /rescue-ops/_clock/set_current_utc` with mandatory default `2026-08-01T00:00:00Z`); Errors: 44; Validations: 25 ordered priorities; Roles: 10 (segregation-of-duties model: euthanasia certifier ≠ proposer, adoption approver ≠ home-check completer; entity-backed Adopter/Sponsor/Volunteer/Veterinarian/Farrier identities with registration exemption)
- Concurrency: 2 true OCC rules (`rehab-plan-create-stale-horse`, `care-plan-create-stale-horse`, both 412 on `expected_horse_version`)
- §1.8 instances: 20 (every rule ≥2; dual_variant_calc and boundary_precision_check have 3). All formula-derived asserts were executed as Python and pinned as literals (e.g., ACTUARIAL age-10 total 6059405 vs STRAIGHT_LINE 6930000; feed tight 31.23 vs committed 46.84; pair fee 93750; PO 7494 vs 7493 + surcharge 600 + grand 8094; feed conservation 999.00 == 646.78 + 57.66 + 294.56)
- §1.9 instances: 76 (63 active + 13 `excluded_because` stubs) across all 9 taxonomy sections

**Difficulty rating: beyond Expert band.** Expert caps at 10–15 entities / 20–32 endpoints; this scaffold carries 22 entities / 105 endpoints with density-first coupling: depth-3 transitive cascades from two distinct triggers (adoption finalize → horse → sponsorship → sponsor recompute; failed follow-up → application return → horse re-entry → AUTO_RETURN quarantine), two temporal-overlap geometries (practitioner half-open + 15-min buffer vs stall closed-interval + quarantine-barn disinfection gap), three dual-variant calculation domains, validation priority conflicts across distinct category pairs (state×safety, temporal×fiscal), inclusive/exclusive boundary pins (48h exam, 72h cooling-off, 19250-cent subsidy, exactly-40 reliability gate, 38500-cent funding equality), and a replay-audited OCC supersede pattern.

**Verification:** `scaffold_lint.py` verdict block (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (999 calls scanned, 0 violations). Additional custom audits all pass: placeholder closure (zero unbound `${var}`), instance-name uniqueness across both design files, grounds resolvability against §1.1–§1.7, enum discipline in payloads, per-instance clock monotonicity, entity-backed role identity discipline, forbidden-vocabulary scan, and call-by-call state-machine replay (which caught and fixed one real bug — a competing application created after the horse left ADOPTABLE was reordered before the approve call). No sibling task directories were inspected.

## Step 3: Copy Shared Files — 2026-08-15T02:14:30.766493247Z

Copied `./INSTRUCTION.md` to `tasks/task_1933_equine_rescue_sanctuary_operations/workspace/INSTRUCTION.md` (bash-only step, no subagent).

## Step 4: Generate PRD — 2026-08-15T02:26:24.379636806Z

PRD generation complete. The document was written to `/home/ubuntu/github/CodingPRD/tasks/task_1933_equine_rescue_sanctuary_operations/workspace/PRD.md` (420 lines). Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, and no sibling task was consulted.

## Section list

- **1. Introduction** (3 paragraphs: business context, collision/consistency angle, reader's map)
- **2. Global Specifications & System-Wide Principles** — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (emitted byte-verbatim from `section-2.2-response-structure.md`, verified by string comparison) · 2.3 Pagination · 2.4 The Sanctuary Logical Clock · 2.5 Common Resource Properties and the Append-Only Ledgers · 2.6 Optimistic Concurrency on the Horse Record · 2.7 Validation Cascade and Failure Precedence (all 25 tiers, ordered) · 2.8 Resident Posture and Terminal Lockdown · 2.9 Numeric Precision, Rounding, and Monetary Representation · 2.10 Nested Resource Resolution
- **3. Business Logic & Workflows** (9 subsections) — 3.1 Intake, Housing, and the Quarantine Watch · 3.2 Rehabilitation Plans and Practitioner Care · 3.3 The Adoption Pipeline: Applications and Home Checks · 3.4 Approval, Fee Determination, and Settlement · 3.5 Finalization, Follow-Up Visits, and the Return Cascade · 3.6 Sanctuary Care and Sponsorship Funding · 3.7 Feed Purchasing, Supply Projection, and the Daily Close · 3.8 Volunteer Shifts and Reliability Standing · 3.9 End-of-Life Governance
- **4. Endpoint Definitions** (status-code paragraph + 105-row, 4-column table — exact match to scaffold endpoint set)
- **5. Error Code Catalogue** (44-row, 2-column table)

## Zero-Silence Rule self-audit (scaffold §1.1–§1.7)

- **§1.1 Entities**: 113/113 field names present verbatim in backticks (incl. `purchase_order_id`, added on a repair pass); structured content placed (defaults 5/0/0/50/true/false, ranges, append-only exclusion of `updated_at`/`version` on DailyHealthLog and FeedDayClose).
- **§1.2 State machines**: 80/80 transitions expressed with from/to states, preconditions paired to error IDs, and all cascades spelled out (adoption finalize, four-link return cascade, euthanasia execute, quarantine re-entry, practitioner deactivation, per-branch sponsorship PLEDGED/ACTIVE/LAPSED → COMPLETED/CANCELLED asymmetries rendered with equal density).
- **§1.2.1 Concurrency rules**: 2/2 OCC entries fully expressed — both write endpoints named, `expected_horse_version` as non-optional input, mismatch rejected with `ERR_STALE_HORSE_VERSION` (412); stated that no other endpoint accepts a version field.
- **§1.3 Calculations**: 7/7 expressed in precise prose (ration thresholds 2%/2.5%/4.0 lbs; lifespan 25/22/28; actuarial bands 38500/45200/52800/61500 with survival 0.97/0.89/0.78 raised to the one-twelfth power, final-sum-only rounding; fee steps pinned 1→4 with 19250 subsidy threshold; TIGHT vs COMMITTED supply variants with zero-demand guard and strict <30 reorder; per-lot-before-sum purchase rounding incl. the 7494-vs-7493 counter-example; quarantine timing with inclusive release/exam and exclusive 72h fever boundaries; reliability clamp formula). 54/54 constant spot-checks pass; fuzzy-word scan clean.
- **§1.4 Validations**: 25/25 priorities rendered as an explicit ordered cascade in §2.7, including the tier-18 fixed sub-order (release-date → exam staleness → fever) and the registration-endpoint identity exemption; `applies_to` scopes enumerated in §3 narratives.
- **§1.5 Endpoints**: 105/105 in the §4 table, no missing/extra.
- **§1.6 Errors**: 44/44 in §5 and every ID mentioned in §2/§3 prose.
- **§1.7 Roles**: 10/10 named with exact spelling; every `identity:` field translated (entity-backed vs opaque, incl. specialty-matching for Veterinarian/Farrier and self-scope ownership rules).

Contract 3 (§3 path purity): 844 backticked tokens scanned in §3 — 0 paths, 0 bare HTTP methods, 0 method+path combinations. **All three hard contracts: PASS.**

## Step 5: Generate Unit Tests — 2026-08-15T03:01:46.424455683Z
Generation complete. Summary:

## Tests generated

**Queue A (Difficulty)** — 38 tests covering 19 of 20 instances (each translated instance has exactly 2 tests, both carrying the `Design: Difficulty/<rule_id>/<instance.name>` tag):
- All three `dual_variant_calc` instances (care-plan ACTUARIAL vs STRAIGHT_LINE — pre-computed literals 6059405/33663 and 1596322/44342 independently re-verified numerically; feed TIGHT 31.23 vs COMMITTED 46.84; fee QUOTED 90000 vs FINAL 100000 with `ERR_ADOPTION_FEE_UNPAID` gate)
- Both `combinatorial_formula` (pair fee 93750; per-lot rounding 7494 vs 7493, surcharge 600, grand 8094)
- Both `non_linear_state_machine`, both `transitive_cascade`, both `priority_pair_validation_conflict` (legitimate because PRD §2.7 explicitly pins the stop-at-first-failing-tier cascade), all three `boundary_precision_check`, both `cross_entity_state_dependency`, one of two `resource_temporal_overlap`, both `compensating_invariant`.

**Queue B (Corner)** — 62 tests covering 62 of 64 non-stub instances (1 test each, `Design: Corner/<section>/<instance.name>`). All 13 `excluded_because:` stubs left untranslated; every stub's `difficulty_instance` pointer verified to resolve.

## Instances skipped (3) — PRD-first two-condition failures

1. **Difficulty/resource_temporal_overlap/stall_closed_interval_disinfection_gap** — unique-derivability (error-precedence): the lead assertion requires `ERR_STALL_OVERLAP` when one request violates both the overlap and the quarantine-barn gap rule; PRD §2.7 tier 15 lists both errors in a single tier with no intra-tier ordering (in contrast to the explicitly ordered tier-18 quarantine triplet).
2. **Corner/entities/bonded_companion_fk_reverse_lookup** — no verbatim PRD coverage: the `bonded_companion_id` list filter is not enumerated in PRD §4, and `bonded_companion_id` is absent from the §2.7 tier-5 body-FK list, so the dangling-FK rejection is not uniquely derivable.
3. **Corner/endpoints/applications_filtered_by_horse** — no verbatim PRD coverage: the `horse_id` filter parameter on GET /adoption-applications is never enumerated in PRD prose.

Sanctioned assertion-level relaxations (per the skill's final-pass "remove or relax" rule, not instance skips): initial-`version` literals replaced by relative "+1 per modification" assertions (PRD §2.5 pins increments, not the starting value); `usable_lbs`/`inbound_ordered_lbs` literal field assertions dropped from feed-summary tests (field names never appear in PRD; `daily_demand_lbs`, `days_of_supply_tight/committed`, `reorder_required` retained).

## Audit results
- 100 tests collected cleanly by pytest; all modules compile/import.
- Every test docstring carries exactly one Design tag as its last line; all tags resolve to real non-stub instances (queue A ≥2 tests each, queue B ≥1).
- 154 docstring quotes of ≥8 words all survive verbatim whitespace-normalized grep of PRD.md.
- No `skip`/`skipif`/`xfail` markers; no scaffold references in generated code.

## Files

**test_helpers/** (`/home/ubuntu/github/CodingPRD/tasks/task_1933_equine_rescue_sanctuary_operations/test_helpers/`): `__init__.py` (barrel), `types.py` (22 entity TypedDicts incl. append-only ledger variants, 25 enums), `api_client.py` (67 endpoint methods), `api_errors.py` (44-error catalog registered via `set_error_http_status_map`), `assertions.py` (22 entity assertions + funding invariant), `factories.py` (21 payload factories), `constants.py` (PRD thresholds), `test_users.py` (opaque-role constants + 5 entity-backed `make_*_headers` builders), `fixtures.py` (composite chains: intake→eval→clear→release, sanctuary designation, application pipeline to HOME_CHECK_PASSED/APPROVED/FINALIZED, sponsorship/care-plan/PO/shift/euthanasia builders).

**test_suite/** (`.../test_suite/`): `conftest.py` + `test_01_horse_intake_ration_and_envelope.py` (11), `test_02_auth_and_rbac.py` (6), `test_03_quarantine_and_housing.py` (13), `test_04_rehab_and_care_appointments.py` (8), `test_05_adoption_pipeline.py` (14), `test_06_adoption_fees_and_finalize.py` (11), `test_07_finalize_cascades_and_returns.py` (8), `test_08_sanctuary_sponsorship_and_end_of_life.py` (13), `test_09_feed_program.py` (11), `test_10_volunteers_and_shifts.py` (5).

## Step 6: Generate Implementation — 2026-08-15T03:01:46.441700884Z
Implementation complete and verified. Summary follows.

## File list

All under `/home/ubuntu/github/CodingPRD/tasks/task_1933_equine_rescue_sanctuary_operations/workspace/implementation/`:

- `start.sh` — guarded pip install (no-op once Flask importable), `exec python3 app.py`, executable
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask entry, blueprint registration, `ApiError`/404/405/500 envelope handlers, `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory dict stores (empty at boot, zero seeding) + insertion sequence
- `clock.py` — logical clock, fixed default `2026-08-01T00:00:00Z`
- `errors.py` — `ApiError` + all 44 error IDs with their HTTP statuses
- `response.py` — envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list meta adds `limit`/`offset`/`total_count`/`has_more`
- `auth.py` — tiers 1–3: header presence/declared role (401), entity-backed identity resolution incl. specialty match (403, with the three registration-endpoint exemptions), role-list authorization (403)
- `util.py` — body/field/datetime/HH:MM validators, minute-precision truncation, pagination parsing (limit 1..100, default 10)
- `calc.py` — daily ration (Decimal, 1dp), lifetime care projection (STRAIGHT_LINE + ACTUARIAL compounding survival, final-only rounding), adoption fee 4-step pinned order, feed demand/seasonal multipliers, PO per-lot rounding/surcharge, volunteer reliability clamp
- `services.py` — entity factory (ledger variant omits `updated_at`/`version`), cascade helpers: sponsor-status recompute, care-plan coverage recompute, protocol creation/extension, appointment cancellation cascades, adoption finalize cascade (stall end, sponsorship completion, companion adoption, competing-application auto-reject, follow-up creation), return cascade, EOL restore/deceased cascades
- `serializers.py` — datetime→ISO8601 3-fractional-digit `Z`, Decimal→number, internal keys stripped
- `routes/`: `clock_routes.py`, `horses.py`, `quarantine.py` (evaluations/protocols/health-logs), `rehab.py` (plans/practitioners/appointments), `housing.py` (stalls/assignments), `adoption.py` (adopters/applications/home-checks/follow-ups), `sponsorship.py` (sponsors/sponsorships/care-plans), `feed.py` (POs/lots/summary/close-day/day-closes), `volunteers.py` (volunteers/shifts), `euthanasia.py`

## Coverage

- **Endpoints: 105/105** — registered route count matches the PRD §4 table exactly (verified by grep against the route decorators, and each was exercised in smoke runs).
- **Error catalogue: 44/44** — every error ID from PRD §5 is implemented with its exact HTTP status; smoke tests directly observed 40 of them firing (the remaining four — e.g. `ERR_NOT_FOUND` path variants — share the same code paths as observed sibling checks).
- Smoke verification (7 suites, ~180 assertions, all passing) covered: envelope shape, pagination meta and bounds, auth tiers, every state machine transition and terminal lockdown, all cascades (fever +7, eval-FAIL +7, re-quarantine appointment cancellation, practitioner deactivation, adoption finalize incl. companion, return cascade with 50% refund, deceased cascade), OCC 412 on both plan endpoints, quarantine clear triplet in fixed order with exact 48h/72h/release-date boundaries, fee QUOTED/FINAL divergence via sponsor lapse, subsidy threshold boundary (19250 vs 19249), per-lot rounding counter-example (3×333 lbs @ 7.5c → 7494 vs naive 7493; surcharge 600; grand 8094), FEFO close-day with waste-first ordering and `ERR_DAY_ALREADY_CLOSED`, reliability gate at exactly 40, duty segregation on both euthanasia certify and adoption approve, precedence block with equal-timestamp exemption, home-check 180-day boundary, and `bash start.sh` booting cleanly on a custom PORT.

## PRD interpretation decisions (ambiguous prose)

1. **Finalize check ordering** — §3.5's narrative lists fee-before-pickup, but §2.7's normative tier cascade (17 cooling-off → 19 pickup → 22 bonded → 25 fiscal) wins; implemented in tier order.
2. **Shift-claim ordering** — scaffold lists skill/reliability before overlap; PRD §2.7 puts overlap at tier 16, specialty/skill/reliability at tier 23. Implemented PRD order (overlap first, then ACTIVE → reliability → skill).
3. **Feed demand rounding** — `daily_demand_lbs` is rounded only for storage/display in the summary; the days-of-supply division and close-day demand use the exact unrounded demand, rounding only the final outputs (§2.9 intermediate-rounding principle).
4. **Care-plan funding at creation** — `funding_coverage_cents` initialized to the horse's current ACTIVE-pledge sum at plan creation (per the "is the sum of..." definition), then recomputed on every sponsorship mutation; recomputes bump the plan's `version` only when a value actually changes.
5. **Stall zone rule is one-directional** — only QUARANTINE horses are restricted (to QUARANTINE_BARN); non-quarantine horses may occupy any zone, per scaffold tier-24 wording.
6. **Stall overlap/gap scope** — all assignments on the stall (ACTIVE and ENDED) count as occupancy history; QUARANTINE_BARN gap requires ≥1 full calendar day between windows in either direction (e.g. prev ends Aug 5 → next starts Aug 7).
7. **`bonded_companion_id` FK** — validated on create and PATCH with `ERR_HORSE_NOT_FOUND` (it is a horse reference though not named in tier 5's list).
8. **Version starts at 1** on creation; every mutation including cascaded ones increments it and refreshes `updated_at`; ownership failures are 403 checked after request-shape validation and before state checks.
9. **`emergency_attestation` required** on certify (endpoint table lists it without the `?` optional marker).
10. **Volunteer auto-suspension** is implemented exactly as specified (`< 20` after a no-show) even though the ≥40 claim gate makes it unreachable through claim→no-show loops alone — implemented as written, not "fixed".

## Step 7: Run Tests and Iterate — 2026-08-15T03:10:42.138813157Z
## Summary

**Result: clean 8-round parallel sweep — 100/100 tests passing in every round.**

### Iterations run
2 sweeps (16 round-runs total).
- Sweep 1: 91/100 in all 8 rounds — the same 9 tests failing deterministically (no flakiness; the "FAILED" count variance in raw interleaved output was a line-merging artifact).
- Sweep 2 (after fixes): 100/100 × 8 rounds.

### Tests deleted
None. Every failing test traced to a verbatim PRD rule; the two root causes were one implementation bug and one test-side over-constraint pattern.

### Fixes applied to `implementation/`
- `/home/ubuntu/github/CodingPRD/tasks/task_1933_equine_rescue_sanctuary_operations/workspace/implementation/util.py` — `new_id()`: `uuid.uuid4().hex` → `str(uuid.uuid4())`. PRD §2.5 verbatim: "`id` (string): a server-minted UUID, with no type prefix." The dashless hex form failed the benchmark framework's canonical-UUID validator (`is_valid_uuid` requires 8-4-4-4-12 dashed form, the standard reading of "a UUID" as a JSON string). This single fix cleared 4 tests: `test_01::test_horse_creation_initial_state`, `test_01::test_horse_defaults_applied`, `test_01::test_health_log_immutable_no_version`, and the first failure point of `test_03::test_clear_stamps_cleared_at_boundary_instant`.

### Fixes applied to `test_helpers/`
- `/home/ubuntu/github/CodingPRD/tasks/task_1933_equine_rescue_sanctuary_operations/test_helpers/assertions.py` — added `assert_same_instant(actual, expected)` (plus private `_parse_instant`). STEP 1c partial-coverage split: PRD pins the *instant* each business timestamp records (§3.1 "stamps `cleared_at`", §3.5 "sets `finalized_at` to the logical now", "with `scheduled_date` set 30, 90, and 180 days after `finalized_at`", "with `end_date` set to the application's `proposed_pickup_date`", §3.9 "Execution stamps `executed_at`", §3.7 "the response reports the `closed_date`"), but PRD states the three-fractional-digit wire format *only* for `created_at`/`updated_at` (§2.5) and `api_request_timestamp` (§2.2) — business datetime fields' format is unstated, so exact-string equality was not uniquely derivable (a faithful reader could emit `...T00:00:00.000Z` or `...T00:00:00Z`; the framework's own `is_iso8601_timestamp` accepts both). The helper keeps the covered instant assertion at full strength and drops only the PRD-silent representation constraint.

### Fixes applied to `test_suite/`
- `test_03_quarantine_and_housing.py` — `test_clear_stamps_cleared_at_boundary_instant`: `cleared_at` string equality → `assert_same_instant` (+ import).
- `test_06_adoption_fees_and_finalize.py` — `test_finalize_stamps_finalized_at_boundary_instant`: `finalized_at` → `assert_same_instant` (+ import).
- `test_07_finalize_cascades_and_returns.py` — `test_finalize_autorejects_competitor_and_ends_stall`: stall `end_date` → `assert_same_instant`; `test_followup_visits_auto_created_at_finalize`: scheduled_date dict string equality → per-key `assert_same_instant` (+ import).
- `test_08_sanctuary_sponsorship_and_end_of_life.py` — `test_euthanasia_full_path_deceased_lockdown`: `executed_at` and stall `end_date` → `assert_same_instant` (+ import).
- `test_09_feed_program.py` — `test_close_day_already_closed_rejected`: both `closed_date` assertions → `assert_same_instant` (+ import).

No assertions were weakened on any PRD-covered rule (error IDs, boundaries, state transitions all intact); no skip/xfail added; no non-PRD capability added to the implementation.

## Step 8: Finalize PRD — 2026-08-15T03:14:07.567113702Z
## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1933_equine_rescue_sanctuary_operations/workspace/PRD_FINALIZED.md`

**Line counts / delta:** PRD.md = 420 lines; PRD_FINALIZED.md = 422 lines; +2 lines (+0.48%). Two edits, both in §2.5; nothing else touched.

### Changes (one bullet each)

- **§2.5 `id` bullet — revise** — "a server-minted UUID, with no type prefix" now pins the canonical hyphenated 8-4-4-4-12 hexadecimal form (example given). Traces to the step_7_diff implementation fix — `workspace/implementation/util.py:15-17` (`new_id()`: `uuid.uuid4().hex` → `str(uuid.uuid4())`); dashless hex failed the framework's `is_valid_uuid` validator, proving the old wording did not uniquely determine the wire form.
- **§2.5, after the common-fields bullets — insert** — one paragraph pinning that every datetime-valued field the server returns (all §3 business date/timestamp fields plus the clock endpoint's `current_utc`) renders as ISO 8601 UTC with exactly three fractional digits, matching `created_at`. Traces to the step_7_diff test_helpers fix (`assert_same_instant`) and the five test_suite fixes (test_03, test_06, test_07 ×2, test_08, test_09) — impl renders every datetime via `iso_z` (`workspace/implementation/util.py:20-23`, `serializers.py:19-20`) but PRD stated the format only for `created_at`/`updated_at`/`api_request_timestamp`.

### Per-edit pre-edit search log

**Edit 1 (UUID form):**
- (a) Subject: format of the server-minted `id` field.
- (b) Paths enumerated: `util.py:15-17` (`new_id`, sole definition); grep for `new_id` confirms sole caller `services.py:22` (`new_entity`); grep across `routes/` confirms all entity creation in all 9 route modules flows through `new_entity` (23 call sites) or helpers (`create_protocol`, `create_follow_ups`) that call it — no other `"id"` minting exists. `response.py:13` `api_request_id` (`"req_" + secrets.token_hex(12)`) is a different field already pinned by §2.2, outside the edit's scope.
- (c) Wording adjustment: avoided pinning lowercase explicitly (framework regex is case-insensitive; impl emits lowercase naturally) and avoided naming Python — used "canonical hyphenated 8-4-4-4-12 hexadecimal form" plus a concrete example, keeping the sentence true for every enumerated path without over-pinning.

**Edit 2 (datetime wire format):**
- (a) Subject: wire representation of datetime-valued fields in server responses.
- (b) Paths enumerated: `serializers.py:14-25` (`serialize` applies `iso_z` to every `datetime` on every record — 111 route call sites); `util.py:20-23` (`iso_z` definition, exactly three fractional digits + `Z`); direct emissions `feed.py:270` (`closed_date`) and `clock_routes.py:17` (`current_utc`), both `iso_z`; `response.py:11` (`api_request_timestamp`, same format, already pinned §2.2). Verified every datetime-storing field originates from `parse_dt` or `clock.now()` across housing/adoption/quarantine/rehab/volunteers/feed/sponsorship/euthanasia routes (`start_date`, `end_date`, `proposed_pickup_date`, `scheduled_date`, `shift_date`, `expiry_date`, `close_date`, `scheduled_start`, `scheduled_end`, plus all server-stamped `*_at` fields and timedelta-derived follow-up `scheduled_date` / cascade `end_date`). Checked `volunteers.py:104-117`: `start_time`/`end_time` are stored and echoed as raw HH:MM strings — not datetimes, correctly outside the claim. `volunteers.py:143` `.date().isoformat()` is filter-comparison only, not output.
- (c) Wording adjustment: initial draft risked a partial field list being read as exhaustive; final wording leads with the universal clause ("every datetime-valued field the server returns") and explicitly enumerates all 22 business datetime fields confirmed present in the impl (verified complete against a grep-extracted field-name set), so no enumerated path is mis-described and no unlisted datetime field exists to be excluded by implication.

No other step_7_diff items required PRD edits (no test deletions; no other implementation fixes; the remaining step_7 entries are the test-side consumers of Edit 2's silence).

## Step 9: Complete PRD — 2026-08-15T03:26:42.666423872Z
All 30 diff hunks match the intended edits exactly. The file is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1933_equine_rescue_sanctuary_operations/workspace/PRD_COMPLETED.md`.

## Summary

**Source:** `PRD_FINALIZED.md` (existed; copied to `PRD_COMPLETED.md`, then edited in place).
**Size:** 422 lines / 75,719 chars → 425 lines / 80,134 chars (**+3 lines, +4,374 chars**).
**Counts:** 29 ambiguity-pins, 6 mismatch-revisions (35 logical changes across 30 diff hunks; all 100 existing tests already pass against this implementation).

### Mismatch-revisions (PRD described behavior impl does not exhibit)

- §2.8 — revise — mismatch — narrowed the `DECEASED` total-lockdown claim: only horse-record mutations and horse state transitions fail with `ERR_INVALID_STATE`; residency/adoptability-gated endpoints keep their own codes, and evaluation scheduling/completion, health-log append, and stall assignment never inspect horse posture — implementation/routes/horses.py:198, routes/quarantine.py:55,196, routes/housing.py:97
- §2.9 — revise — mismatch — carved out two full-timestamp-precision comparisons from the blanket minute-precision rule: the 90-day refund boundary and feed expiry comparisons — implementation/services.py:201, routes/feed.py:174,228
- §3.1 — revise — mismatch — disinfection-gap rule applies to every other assignment on the stall in either direction, not just "the previous occupant's window" — implementation/routes/housing.py:88-94,125
- §3.2 — revise — mismatch — `rehab_plan_id` is always optional on booking; PRD's "required when plan-linked" requirement does not exist — implementation/routes/rehab.py:251
- §3.6 — revise — mismatch — sponsorship cancel request field is `reason` (recorded onto `cancellation_reason`), not `cancellation_reason` — implementation/routes/sponsorship.py:207,213-214
- §3.6 — revise — mismatch — care-plan `funding_coverage_cents` initializes at creation to the horse's then-current ACTIVE pledge sum rather than "starting from 0" — implementation/routes/sponsorship.py:250

### Ambiguity-pins (PRD silent; pinned to impl)

- §2.1 — insert — ambiguity — Adopter/Sponsor read scoping on applications/sponsorships: lists silently scope to caller's own id, direct reads of others' records fail `ERR_FORBIDDEN` — implementation/routes/adoption.py:204-206,214, routes/sponsorship.py:121-122,135-136
- §2.2 — revise — ambiguity — error envelope covers 4xx or 5xx (ERR_INTERNAL exists) — implementation/app.py:60-65
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` fail `ERR_INVALID_REQUEST` — implementation/util.py:127-149
- §2.3 — insert — ambiguity — same-instant ties keep creation order; list endpoints accept exact-match field filters (booleans only `true`/`false`; unknown params ignored; shift `shift_date` filter matches bare date or full timestamp) — implementation/util.py:152-170, routes/volunteers.py:138-144
- §2.3 — insert — ambiguity — `has_more` is true exactly when `offset` + returned count < `total_count` — implementation/response.py:28
- §2.7 tier 5 — revise — ambiguity — `bonded_companion_id` body FK resolves as a horse (`ERR_HORSE_NOT_FOUND`) — implementation/routes/horses.py:64-67
- §2.7 tier 6 — insert — ambiguity — non-JSON-object request bodies rejected outright — implementation/util.py:47-53
- §2.7 — insert — ambiguity — ownership-check ordering: from-state first on appointment confirm/complete, sponsorship activate/reinstate/cancel, shift release; ownership after body validation on application/sponsorship creation, fee payment, withdrawal — implementation/routes/rehab.py:322-325,347-350, routes/sponsorship.py:162-164,209-210, routes/volunteers.py:193-195, routes/adoption.py:155,315-316,335-337
- §2.10 — insert — ambiguity — undeclared paths/unsupported methods fail `ERR_NOT_FOUND` in the same envelope — implementation/app.py:50-57
- §3.1 — insert — ambiguity — horse PATCH increments `version` on every accepted call, even a no-op — implementation/routes/horses.py:209
- §3.1 — insert — ambiguity — supplied assignment `end_date` earlier (by calendar date) than `start_date` refused `ERR_INVALID_REQUEST` — implementation/routes/housing.py:111-114
- §3.1 — insert — ambiguity — `temp_f` bounds 95.0/110.0 are inclusive — implementation/routes/quarantine.py:205
- §3.1 — insert — ambiguity — protocol-extend `days` must be a positive integer — implementation/routes/quarantine.py:148-150
- §3.2 — insert — ambiguity — completion requires `actual_cost_cents` as an integer ≥ 0; a missing value surfaces only after from-state and ownership checks — implementation/routes/rehab.py:342-352
- §3.2 — insert — ambiguity — graduation's 30-day medical-exam window counts an exam exactly 30 days old — implementation/routes/horses.py:91
- §3.3 — insert — ambiguity — adopter block takes a required `reason` — implementation/routes/adoption.py:118
- §3.3 — insert — ambiguity — `quoted_fee_cents`/`final_fee_cents` stay null until approval/finalization — implementation/routes/adoption.py:181-182
- §3.3 — revise — ambiguity — home-check completion is refused `ERR_INVALID_STATE` unless the application sits in `HOME_CHECK_SCHEDULED` and the check is its most recently created one — implementation/routes/adoption.py:439-448
- §3.4 — insert — ambiguity — 180-day home-check freshness counts a check exactly 180 days old — implementation/routes/adoption.py:258
- §3.5 — insert — ambiguity — rejection `reason` is a required field — implementation/routes/adoption.py:297
- §3.5 — insert — ambiguity — refund window: exactly 90 days after `finalized_at` still earns the half refund — implementation/services.py:201
- §3.6 — insert — ambiguity — plans track funding only in `DRAFT`/`APPROVED`; `SUPERSEDED`/`CLOSED` plans keep last figures — implementation/services.py:60-75
- §3.7 — insert — ambiguity — draft purchase order holds `delivery_surcharge_cents`/`grand_total_cents` null until completion — implementation/routes/feed.py:58-59
- §3.7 — insert — ambiguity — receipt quantity must be above zero (`ERR_INVALID_REQUEST`); receipt call returns the updated purchase order, not the lot — implementation/routes/feed.py:103-105,135
- §3.7 — insert — ambiguity — received quantity is rounded half up to two decimals before accruing/anchoring the lot — implementation/routes/feed.py:109
- §3.7 — insert — ambiguity — summary entries in fixed order GRASS_HAY/ALFALFA/GRAIN/SUPPLEMENT with pinned field set (`feed_type`, `daily_demand_lbs`, `usable_lbs`, `inbound_ordered_lbs`, `seasonal_multiplier`, both days-of-supply figures, `reorder_required`) — implementation/routes/feed.py:170,191-201
- §3.7 — insert — ambiguity — `usable_lbs`/`inbound_ordered_lbs` rounded half up to two decimals like demand — implementation/routes/feed.py:195-196
- §3.7 — insert — ambiguity — close-day response reports `consumed_lbs`/`wasted_lbs` as objects keyed by feed type — implementation/routes/feed.py:263-271
- §3.7 — insert — ambiguity — FEFO ties fall back to creation order within the same instant — implementation/routes/feed.py:240
- §3.9 — insert — ambiguity — `emergency_attestation` is a required boolean on certify — implementation/routes/euthanasia.py:108
- §5 — insert — ambiguity — added `ERR_INTERNAL` (500) row to the error catalogue — implementation/app.py:64

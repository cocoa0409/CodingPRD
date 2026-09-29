# Worklog — task_2605_cord_blood_banking_unit_release

## Step 1: Create task directory — 2026-09-03T18:25:28.925Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2605_cord_blood_banking_unit_release` and `.../workspace`. Index pre-assigned (2605) by the invoking command; no index scan performed.

## Step 2: Generate scaffold — 2026-09-03T20:17:52.744Z

All three artifacts are complete and lint-clean.

## Files (all at `/home/ubuntu/github/CodingPRD/tasks/task_2605_cord_blood_banking_unit_release/`)

| File | Lines | Top-level key |
|---|---|---|
| `SCAFFOLD.yaml` | 3,167 | §1.0–§1.7 only (grep for `scaffold_difficulty_design`/`scaffold_corner_design` → 0 hits) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2,068 | `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4,423 | `scaffold_corner_design` |

All three parse with `yaml.safe_load`. Final `scaffold_lint.py` verdict: **clean lint** — 1,208 §1.8+§1.9 calls conform to §1.5, all §1.1 FKs reverse-reachable.

## SCAFFOLD.yaml counts
13 entities · 63 endpoints · 15 state machines · 18 calculations · 35 validations (priority 1–35) · 53 error codes · 10 roles · 2 `concurrency_rules`. Profile: `difficulty_level: expert_plus`, `state_machine_shape: parallel`, `role_model: segregation_of_duties`, `consistency_model: immediate`, `entity_topology: flat`, `complexity_layers: [optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`, `api_prefix: /cbb`.

## §1.8 — 9 difficulty rules × 2 instances = 18
dual-variant divergence (PRE_CRYO vs POST_THAW dose; prorated vs anniversary storage fee) · pinned rounding order (per-line invoice mode B; settlement tier keyed on pre-fee subtotal mode C) · parallel multi-axis state · fork-join reservation side-effect sets · cascade depth 4 (temperature) and depth 3 (nightly delinquency) · cross-family priority masking (409 over 402; 422 over 409) · inclusive boundaries (48.00 h receipt; 900 M TNC public floor) · cross-entity gating (screening row state; holding-tank status) · interval semantics (closed hold intervals with symmetric 24 h buffer; half-open maintenance window) · conserved invariants (tank slots across confirm→cancel; account balance across delinquency→full payment).

## §1.9 — all 9 guide sections, 91 instances (62 concrete recipes + 29 `excluded_because` stubs)
entities 12 · state_machines 15 (5 stubs) · calculations 15 (9) · validations 9 (3) · endpoints 6 (2) · errors 24 (8) · rbac 4 · cross_cutting_complexity_layers 5 (2) · consistency_model 1. Every `claim_type` row of `claim-extraction-guide.md` is represented; every stub names a real §1.8 instance; all 109 instance names unique across both design files; **all 53 §1.6 error codes are triggered somewhere in §1.8/§1.9**.

## Design adjudications made
1. **ERR_PROGRAM_TYPE_MISMATCH was unreachable** — a private unit is `PRIVATE_STORED` post-cryo with no edge to `LISTED`, so priority 9 always masked priority 21, and the invoice branch was dead (accounts only exist for private enrollments). Extended validation 21 and the §1.6 condition to also cover `POST /cbb/storage-accounts` (a StorageAccount on a `PUBLIC_DONATION` enrollment), which is now the conditional_validation instance.
2. **ERR_CONSENT_NOT_CURRENT** could only be shown unambiguously at `POST /cbb/units/{id}/cryopreserve`, whose §1.2 edge preconditions don't mention consent (at kit dispatch, priority 9 and 11 contend).
3. **ERR_INVALID_RESERVATION_STATE** is proved with a replayed *decline* — the only reservation action that never moves the unit's availability axis, so the co-priority ERR_INVALID_UNIT_STATE cannot shadow it.
4. **ERR_DUPLICATE_ACTIVE_LISTING vs ERR_STALE_UNIT_VERSION**: the same second-listing call yields 409/23 with a re-read version and 412/8 with a stale one; suspending first puts the unit in `UNAVAILABLE` so priority 9 stays silent.
5. **ERR_INVALID_INVOICE_STATE beats ERR_PAYMENT_EXCEEDS_BALANCE** on a PAID invoice (priority 9 < 35) — stated explicitly.
6. **ERR_NO_QUALITY_TEST before ERR_STERILITY_POSITIVE**: priority 15 has no row to read when 16 is violated, so the §1.3 formula order overrides numeric priority (the cascading_validation instance).
7. **ERR_UNIT_NOT_ELIGIBLE at reservation** cannot be shadowed by ERR_MATERNAL_SCREENING_INCOMPLETE because priority 13's `applies_to` excludes `POST /cbb/reservations`.
8. **Cumulative excursion boundary** is proved with two tanks and one unit (121 min refuses the freeze, exactly 120 accepts) since a unit can only be cryopreserved once.
9. **`Reservation.settlement_total_cents` is null on release of a unit with no StorageAccount**, per §1.3's `disposition_settlement` trigger clause ("only when storage_account_id is not null"), which overrides the looser §1.2 side-effect wording — the PRD must keep this reading.
10. GET query parameters with declared required inputs are expressed as `payload:` (lint check (c) reads `payload` only).

## Step 3: Copy shared files — 2026-09-03T20:18:14.738Z

Copied `./INSTRUCTION.md` → `tasks/task_2605_cord_blood_banking_unit_release/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T20:35:29.842Z

PRD complete and verified.

**Output:** `workspace/PRD.md` — **518 lines / 111,605 bytes**, written incrementally (initial create + 8 `cat >>` appends, no single Write near the 64k cap). `tail -40` confirms it ends cleanly on the final `ERR_PAYMENT_EXCEEDS_BALANCE | 422` row of the §5 table — a completed final section, no mid-sentence truncation, no audit footer.

**Sections written (30 headings)**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications, twelve subsections: 2.1 RBAC (10 roles, entity-backed vs opaque identity, both ownership scopes), 2.2 Response Structure (byte-verbatim copy of `section-2.2-response-structure.md`, confirmed by exact-substring check), 2.3 Pagination, 2.4 Common properties / `unit_registry_code` / logical clock, 2.5 Reverse reachability + all 13 404s, 2.6 Cascade discipline & pinned orders, 2.7 OCC on the unit, 2.8 Numeric precision & rounding order, 2.9 The 35-rung adjudication ladder with error IDs, statuses and endpoint scopes + 3 worked precedence examples, 2.10 Segregation of duties, 2.11 Consent as standing precondition, 2.12 The two custody models
- §3 Business Logic, nine subsections: 3.1 enrollment/consent/amendments, 3.2 kit→collection→receipt, 3.3 volume reduction & acceptance test, 3.4 maternal panel & eligibility determination, 3.5 tanks/slots/alarms/excursions/cryopreservation, 3.6 registry publication, 3.7 search/holds/confirm/release, 3.8 billing & delinquency ladder, 3.9 disposal/settlement/nightly batch
- §4 Endpoint Definitions — 63 rows, exactly 4 columns
- §5 Error Code Catalogue — 53 rows, exactly 2 columns

**Coverage confirmation (scripted against SCAFFOLD.yaml)**
- Entities: all 13 covered, including the `QualityTest` `common_fields: false` exception.
- Fields/inputs: 142/142 entity field names, 88/88 endpoint input identifiers, and all response-projection identifiers (search rows, release-summary, the 10 nightly counters, `current_utc`) appear verbatim in backticks — 0 missing.
- Endpoints: 63 rows, exact method/path/role match against the scaffold.
- State machines: all 15 blocks narrated, including the three parallel `CordBloodUnit` axes and both `Enrollment` axes.
- Calculations: all 18 specified in prose, including both dual-variant pairs (`PRE_CRYO`/`POST_THAW`, `ANNIVERSARY_ACCRUAL`/`PRORATED_TERMINATION`) and the pinned rounding orders.
- Validations: 35 priorities enumerated in order in §2.9; every validation error ID reachable (13 404s delegated to the §2.5 enumeration).
- Errors: 53/53 with statuses matching the scaffold.
- Enum values / state names: all 95 declared enum members and 61 state-machine states appear verbatim in backticks.
- Contract 3 (§3 path purity): 0 violations — no backticked token inside §3 begins with `/`, is a bare HTTP method, or combines method+path.
- Table shapes: every pipe row has exactly 2 or 4 cells; no stray column counts.

Two prose defects found and repaired during writing: the public score tier's volume band (now stated once as min 24.0 / max 26.0 mL), and a release-gate attribution that conflicted with §2.9 (release now reports `ERR_OUTSTANDING_BALANCE`; `ERR_ACCOUNT_DELINQUENT` is scoped to hold placement and publication, matching the ladder). Neither withheld design file was opened, and no sibling task directory was read.

**Orchestrator truncation check:** PASS — `tail -25` shows the §5 table completing with all 53 error rows; final heading is `## 5. Error Code Catalogue` at line 462 and the file ends on a complete table row.

## Step 6: Generate implementation — 2026-09-03T21:25:20.000Z

(Steps 5 and 6 were launched concurrently in a single assistant message, per the skill. Step 6 returned first; the Step 5 entry follows below.)

Done. The implementation is complete and verified.

## Files written (all under `workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `app.py` | 62 | `create_app()`, error handlers (ApiError/404/405/400/415/Exception), `0.0.0.0:$PORT` |
| `store.py` | 160 | in-memory `_DB` (13 dicts), logical clock, id/timestamp helpers, `base_row`/`touch`/`public` |
| `calc.py` | 269 | all constants + the 18 calculations (Decimal, ROUND_HALF_UP) |
| `errors.py` | 88 | all 53 error codes → HTTP status, `ApiError`, `fail()` |
| `response.py` | 46 | envelope: `meta`/`response_type`/`data`, object/array/error, `paginate` |
| `middleware.py` | 209 | auth, 10-role RBAC `endpoint()` decorator, body/query validators, pagination |
| `services.py` | 652 | 404 lookups, relations, ownership, recomputes, settlements, 12 cascades, release gate ladder |
| `routes/__init__.py` | 17 | registers 9 blueprints |
| `routes/reads.py` | 341 | all 30 GETs incl. ranked `/cbb/units/search` and `/release-summary` |
| `routes/clinical.py` | 356 | maternal screenings, processing runs, quality tests, eligibility, cryopreserve |
| `routes/holds.py` | 222 | hold / confirm / decline / cancel / release / dispose |
| `routes/enroll.py` | 122 | enrollment, consent, amendment, withdraw |
| `routes/ops.py` | 197 | nightly batch (7 families, 10 counters) + `/_clock/set_current_utc` |
| `routes/lab.py` | 189 | kit dispatch, collection, receipt (mints the unit), rejection |
| `routes/registry.py` | 139 | publish / suspend / resume |
| `routes/tanks.py` | 137 | commission, temperature readings, acknowledge, resolve |
| `routes/billing.py` | 121 | storage accounts, invoices, payments |
| `start.sh` | 10 | reads `$PORT`, binds 0.0.0.0, `exec python3 app.py` in the foreground |
| `requirements.txt` | 1 | `Flask==3.0.3` |

**3338 lines total.** Storage is in-memory dicts only; nothing is seeded, preloaded, or hardcoded — a fresh boot answers every list endpoint with `total_count: 0` and the default clock `2026-08-01T00:00:00Z`.

## Verification

- **Endpoint coverage: 63/63.** A script normalized Flask's `url_map` and diffed it against the scaffold's `method:`/`path:` pairs: `MISSING: []`, `EXTRA: []` (32 POST, 30 GET, 1 PATCH — the count includes `POST /_clock/set_current_utc`, which the scaffold declares as one of the 63).
- **`python3 -m py_compile` passes** on all 17 `.py` files; `__pycache__` cleaned up afterwards.
- **Boot smoke test passed.** Fresh `PORT=<random> bash start.sh` on three separate ports; each bound `0.0.0.0`, served well-formed enveloped responses, and was killed by its own PID only (`kill 1601398`, `kill 1624284`, `kill 1634238`) — never a pattern kill. No stray listeners remain.
- **Four end-to-end walkthroughs (~127 assertions) all pass**, covering: full PUBLIC_DONATION path to release (`blocking_error_id` transitions, `confirmatory_recovery_pct` 94.44, POST_THAW dose gate, enrollment CLOSED); registry suspend/resume with hold cancellation and `ERR_DUPLICATE_ACTIVE_LISTING` vs `ERR_INVALID_UNIT_STATE` discrimination; excursion open → quarantine cascade → acknowledge → benign resolve → full restoration (`duration_minutes` 60, cumulative 60, tank ONLINE); maternal-reactive amendment cascade on a CONFIRMED hold (unit INELIGIBLE/MATERNAL_REACTIVE, listing SUSPENDED, release blocked with `ERR_MATERNAL_SCREENING_REACTIVE`); withdraw cascade (unit DISPOSED/CONSENT_REVOKED/DISCARDED, listing WITHDRAWN, tank slot freed); invoice lines, overpayment 422, nightly PAST_DUE advance with late fee, nightly idempotence; OCC 412, SoD 403, 422 pagination/enum, 401, 403, 404, 405.

Two apparent bugs turned out to be errors in my own test scripts, not the implementation: `X-User-ID` for `ParentGuardian` *is* the Enrollment id (PRD §2.1), and `program_scope` takes `PUBLIC`/`PRIVATE_DIRECTED` (not the program-type enum) — both re-tested and correct.

## Step 5: Generate unit tests — 2026-09-03T22:14:00.000Z

Final verification is complete. Everything compiles and both audits are clean.

## Report

**Output locations (task root, nothing written under `workspace/`)**
- `test_helpers/` — 9 modules, 2,873 lines (`__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`)
- `test_suite/` — `conftest.py` + 20 test modules, 7,010 lines
- `workspace/` still contains only `INSTRUCTION.md`, `PRD.md`, `implementation/` (the concurrent agent's dir, never read or touched)

**Totals**
- 20 test files, **177 test functions**
- `python3 -m py_compile` passes on all 30 generated `.py` files
- Citation audit: `files=20 tests=177 problems=0` (every test carries exactly one trailing `Design:` line; every C1 quote survives a literal grep of `PRD.md`; every quote is a full rule-bearing sentence of >=8 words)
- Tag audit: `diff_instances=18 corner_concrete=62 unresolved=0`, `A covered: 18 with>=2: 18`, `B covered: 62` — no tag points at a non-existent instance, no test is dual-tagged

**Coverage**
- **Queue A (§1.8 depth index): 18/18 instances translated, 0 skipped.** Every instance has >=2 tests (most 3–4); 65 tests live in `test_01`–`test_09`, the rest of queue A's redundancy is distributed across `test_10`–`test_14`.
- **Queue B (§1.9 breadth index): 62/62 concrete instances translated, 0 skipped.** Files `test_10_entity_surfaces` (14), `test_11_state_machine_edges` (14), `test_12_derived_values` (12), `test_13_validation_guards` (11), `test_14_endpoint_contracts` (11), `test_15`–`test_18_error_catalogue_a..d` (32), `test_19_role_boundaries` (8), `test_20_layered_interactions` (8).

**Skipped instances — 29, all of them recipe-less stubs in `SCAFFOLD_CORNER_DESIGN.yaml`**

The corner index contains 91 `name:` blocks. 29 are structural placeholders that carry no `recipe` (marked `STUB -> no recipe`), i.e. they declare a `claim_type` but assert no outcome, so there is nothing for the PRD to uniquely derive and they are not translatable by construction. Per section: `state_machines` 5 (`corner_parallel_axes_of_the_cord_blood_unit`, `corner_alarm_cascade_down_the_tank_inventory`, `corner_cross_entity_delinquency_effects`, `corner_account_balance_ledger_sync`, `corner_guarded_transition_on_a_foreign_entity_state`); `calculations` 9 (`corner_balance_only_counts_unpaid_outstanding_invoices`, `corner_invoice_line_rounding_precision`, `corner_storage_fee_tiered_proration`, `corner_disposition_waterfall_allocation`, `corner_hold_interval_merge_with_buffer`, `corner_eligibility_constraint_propagation`, `corner_dose_variants_diverge_on_identical_inputs`, `corner_dose_variant_selected_per_operation`, `corner_settlement_reconciliation_on_variant_switch`); `validations` 3; `endpoints` 2; `errors` 8 (the `*_error_is_triggerable` row for `ERR_ACCOUNT_DELINQUENT`, `ERR_MATERNAL_SCREENING_INCOMPLETE`, `ERR_MATERNAL_SCREENING_REACTIVE`, `ERR_QUALITY_BELOW_PUBLIC_THRESHOLD`, `ERR_PROCESSING_WINDOW_EXCEEDED`, `ERR_MAINTENANCE_WINDOW_CONFLICT`, `ERR_HOLD_WINDOW_CONFLICT`, `ERR_TANK_NOT_OPERATIONAL`); `cross_cutting_complexity_layers` 2 (`corner_four_level_side_effect_chain_end_to_end`, `corner_both_dose_variants_diverge_on_the_same_unit`). No concrete instance was skipped for PRD silence — the PRD-first filter admitted all 62.

**Three recipe details adjusted rather than asserted** (the instance itself was still translated; the specific sub-assertion had no PRD basis):
- `matched_at == null` on a suspended listing — `RegistryListing`'s declared field list has no `matched_at`; asserted `potency_grade == "A"` and `listing_status == "SUSPENDED"` instead.
- `dose_variant_applied == "POST_THAW"` *before* release — §3.7 sets `PRE_CRYO` at hold placement and only the release paragraph flips it; asserted `post_thaw_dose_x1e7_per_kg == 2.71` pre-release and the `POST_THAW` value on the released row.
- `cancellation_reason_code == "PATIENT_DECEASED"` on a double decline — the PRD pins the code to the centre-supplied `reason_code`, so the test supplies and asserts `ALTERNATIVE_UNIT_SELECTED`.

**One PRD ambiguity resolved on the record:** line 308 is self-contradictory about which rung refuses a republication of a suspended listing. §3.6's precondition list carries no availability-state requirement and `UNAVAILABLE -> LISTED` is an admitted edge, so `ERR_DUPLICATE_ACTIVE_LISTING` (409) is asserted in `test_18`, with `ERR_STALE_UNIT_VERSION` (412) pre-empting it only when the version is stale (`test_20`). An implementer reading line 308 the other way would fail those two tests.

**Orchestrator layout check:** PASS — `test_helpers/` (9 .py) and `test_suite/` (21 .py incl. conftest) are at the task root; `find workspace -type d -name 'test_*'` returns nothing.

## Step 7: Run tests and iterate — 2026-09-03T22:55:15.956Z

Clean sweep verified, with zero skip/xfail markers anywhere in the suite.

## Summary

**Iterations run:** 3 sweeps (8 parallel rounds each). Progression: 16/179 -> 171/179 -> **179/179 in all 8 rounds**.

Fresh verification of the final sweep:
```
results.1..8.json: passed=179 total=179 failed=0 errors=0 skipped=0   (all eight)
```

**Tests deleted:** none. No test asserted a scaffold-only rule; the 179 collected tests all trace to PRD prose. Four individual *assertions* were removed for PRD silence (their parent tests remained covered, per the STEP 1c partial-coverage rule).

**Fixes applied to `implementation/`:**
- `store.py` — new `parse_date()`: parses a calendar date `YYYY-MM-DD` into midnight UTC, also accepting a full RFC 3339 instant and truncating it.
- `middleware.py` — new `v_date()` validator; date-typed body fields no longer go through the timestamp validator.
- `routes/enroll.py` (`expected_delivery_date`), `routes/billing.py` (`prepaid_through_date`, `billing_period_start`, `billing_period_end`), `routes/holds.py` (`intended_transplant_date`) — switched from `v_ts` to `v_date`.

This one defect caused **1288 of the 1304 round-1 failures**: the PRD names instants with an `_at` suffix and dates with a `_date` suffix, and §2.9 rung 5 constrains only "every timestamp". Demanding a time-of-day component on a `_date` field is a restriction with no verbatim PRD basis, so it was fixed in the implementation rather than in the fixtures.

**Fixes applied to `test_helpers/`:** none needed — the fixture layer was PRD-faithful throughout. All eight residual failures were assertion-level mis-translations in `test_suite/`:

- `test_10_entity_surfaces.py` — `assert "data" not in response.json()` contradicted PRD §2.2, which puts `error_id`/`message` *inside* `data` on error responses; replaced with a `response_type == "error"` envelope check.
- `test_13_validation_guards.py` (x2) — expected 200 from `POST /collections/{id}/receive`; PRD §4 states receiving a collection "answers 201 even though the addressed resource is the collection". Now assert 201.
- `test_19_role_boundaries.py` — asserted `eligibility_reason_code is None` after a successful accept; PRD §3.4 says the unit moves "`PENDING -> ELIGIBLE` with an `eligibility_reason_code` of `ACCEPTED`". Tightened to `== "ACCEPTED"`.
- `test_11_state_machine_edges.py` — listed a kit's collections with `IntakeCoordinator` headers, a role the PRD §4 table does not authorize on that endpoint (CollectionSite / ProcessingTechnologist / PlatformAdmin only). The 403 was correct; switched to `CollectionSite`.
- `test_17_error_catalogue_c.py` (x2), `test_20_layered_interactions.py` (x1) — removed `assert hold["confirmed_at"] is None`; `confirmed_at` occurs **0 times** in PRD.md, and §3.7 persists only the status and `intended_transplant_date` on confirmation.
- `test_12_derived_values.py` — removed two `confirmatory["recovery_pct"]` assertions (computed-field silence): the PRD derives the confirmatory recovery figure inside a formula but names it as a response attribute only on the release summary, as `confirmatory_recovery_pct`. The verbatim-covered `outcome == "FAIL"` and `failure_reason_codes == ["VIABILITY"]` assertions were kept.

No assertion was weakened to an HTTP-status check, no exact `error_id` was relaxed, and no PRD-required implementation check was removed. Storage remains in-memory only with no seeded data.

**Orchestrator independent verification:** PASS — 8 `results.*.json` present (all written 22:43), each `passed=179 total=179 failed=0 errors=0 skipped=0`; `grep` for `pytest.mark.skip|xfail` across `test_suite/` + `test_helpers/` = 0 hits; `grep` for `sqlite|json.dump|/tmp/|open(...,'w')` across `implementation/` = 0 hits.

**Step 8 decision:** NOT skipped — Step 7 ran 3 iterations with 5 `implementation/` file fixes and 8 `test_suite/` assertion fixes, so PRD silences exist at those sites.

## Step 8: Finalize PRD — 2026-09-03T23:00:07.924Z

Done. `PRD_FINALIZED.md` written.

## Line counts
- `PRD.md`: 518 lines; `PRD_FINALIZED.md`: 518 lines (0 added/removed).
- 2 lines revised in place -> **0.39 % of lines touched**; final section (§5 Error Code Catalogue, ending at `ERR_PAYMENT_EXCEEDS_BALANCE`) intact.

## Changes
- **§2.9 rung 5** — *revise* — added that date-valued body fields (`expected_delivery_date`, `prepaid_through_date`, `billing_period_start`, `billing_period_end`, `intended_transplant_date`) carry a calendar date, not an instant: bare `YYYY-MM-DD` is accepted, a full RFC 3339 UTC instant is accepted and truncated to its date, anything else is `ERR_VALIDATION_FAILED`; the value is normalized to midnight UTC and thereafter stored/compared/echoed in the standard ISO-8601-UTC-with-3-fractional-digits form, as are the server-derived `due_date` and `paid_through_date`. — `implementation/middleware.py:138` (`v_date`), `implementation/store.py:105` (`parse_date`), `routes/enroll.py:23,32`, `routes/billing.py:25,38-39,55-56,72-75`, `routes/holds.py:93,109`.
- **§3.3 (confirmatory test paragraph)** — *revise* — added that the derived confirmatory recovery figure is not persisted on the `QualityTest` record (no recovery field of its own) and reaches clients only as `confirmatory_recovery_pct` on the release summary, recomputed there. — `routes/clinical.py:205-253` (row shape), `services.py:625-652` (release summary).

## Per-edit pre-edit search log

**Edit 1 — subject: input format, normalization and serialization of date-valued fields.**
(b) Enumerated/read: `middleware.py` all validators (`v_ts` vs `v_date`, `_present`, failure code); `store.py` `_TS_RE`/`parse_ts`/`_DATE_RE`/`parse_date`/`iso`/`pdt`; every `v_date(` callsite (5, all `required=True`) and every `v_ts(` callsite (`collected_at` x2, `freeze_at`, `hold_from`, `hold_until`, `maintenance_window_start/end`, `reading_at`) plus `current_utc` in `routes/ops.py:190-197`; every field name matching `*_date` in the impl (`due_date`, `expected_delivery_date`, `intended_transplant_date`, `paid_through_date`, `prepaid_through_date`) and their derivations (`billing.py:75` `due_date = iso(start + 30d)`, `billing.py:39,117` `paid_through_date`); downstream consumers of the normalized values — `clinical.py:21-46` maternal +/-7-day window against `expected_delivery_date`, `calc.days_past_due`/`calc.unused_days` (both `.date()`-based, so midnight-insensitive), `billing.py:59` `end <= start`; `test_helpers/assertions.py:43,67,258` (type-only assertions, no format equality).
(c) Adjustments: scoped the sentence to the five named *body* fields rather than "fields ending in `_date`" (because `billing_period_start`/`_end` lack that suffix while `due_date`/`paid_through_date` are server-derived, never client-supplied); kept "every timestamp is RFC 3339 UTC" untouched so the eight `v_ts` fields and `current_utc` are unaffected; described `due_date`/`paid_through_date` as *derived* carriers of the same form rather than as inputs.

**Edit 2 — subject: persistence and surfacing of the confirmatory recovery figure.**
(b) Enumerated/grepped: all `recovery` occurrences in impl — `calc.confirmatory_recovery_pct:144`, `calc.confirmatory_outcome:148-157`, `calc.post_thaw_dose:195-200` (recomputes internally), `calc.tnc_recovery_pct:116`; `routes/clinical.py:232-252` confirmatory branch (recovery held in a local, never written to `row`) and `routes/clinical.py:138,165-166` (`tnc_recovery_pct` **is** persisted on `ProcessingRun`); full `QualityTest` row shape at `clinical.py:205-219` and full `Reservation` row shape at `holds.py:63-82` (neither has a recovery key); `services.py:625-652` release summary (the sole emitter of `confirmatory_recovery_pct`); `routes/reads.py` (no recovery projection).
(c) Adjustment: confined the "not persisted" claim to the *confirmatory test record* so it does not contradict `ProcessingRun.tnc_recovery_pct`, and said the release summary *recomputes* it (rather than reading a stored value) to match `services.py:630-632`.

**Items deliberately not patched** (verified PRD-vs-impl agreement, so they were pure test-side bugs): error-envelope `data` containing `error_id`/`message` (§2.2 already normative); `POST /collections/{id}/receive` -> 201 (§4 already states it); `eligibility_reason_code == "ACCEPTED"` (§3.4 already states it); `IntakeCoordinator` not authorized on `/collection-kits/{id}/collections` (§4 table already excludes it); `confirmed_at` — absent from both PRD and impl (`grep confirmed_at implementation/` -> 0 hits), and §3.7 already enumerates exactly what confirmation persists, so nothing needed pinning.

**Orchestrator verification:** PASS — `diff PRD.md PRD_FINALIZED.md` = 4 changed lines (2 revised in place), both files 518 lines, `PRD_FINALIZED.md` tail ends on the complete §5 table.

## Step 9: Complete PRD — 2026-09-03T23:25:00.000Z

Run as **three sequential file-partitioned passes** over `implementation/` (a single-shot Step 9 subagent has historically returned a PRD byte-identical to its input, i.e. the scan never ran; partitioning makes each pass's scope small enough to actually walk). Pass 1 created `PRD_COMPLETED.md` from `PRD_FINALIZED.md`; Passes 2 and 3 edited it in place, additively.

**Cumulative result:** `PRD_FINALIZED.md` 518 lines / 112,654 chars -> `PRD_COMPLETED.md` **522 lines / 136,359 chars** (+4 lines, **+23,705 chars**); `diff` reports 124 changed lines. Tail ends on a complete §5 table row (`ERR_METHOD_NOT_ALLOWED | 405`) — not truncated. **60 total edits: 53 ambiguity-pins, 7 mismatch-revisions.**

### Pass 1 — global/plumbing layer (app.py, store.py, errors.py, response.py, middleware.py, routes/__init__.py, routes/reads.py)
15 edits (9 ambiguity-pins, 4 mismatch-revisions; +6,528 chars, 522 lines):
- §2.2 — revise — ambiguity — `api_request_id` pinned as `req_` + exactly 20 uppercase-alnum chars — response.py:12-16
- §2.1 ¶1 — revise — ambiguity — present-but-empty/whitespace header counts as absent; role comparison case-sensitive (both -> 401) — middleware.py:14-17
- §2.1 "Identity semantics" — revise — **mismatch** — the broad `ParentGuardian` ownership claim was false; the ten-operation enumeration is now declared exhaustive and the un-filtered PG reads named explicitly — routes/reads.py:40-43,73-76,98-101,166-171
- §2.1 ¶3 — revise — **mismatch** — the TransplantCenter ownership check fires on **five** operations, not four (declining was omitted) — routes/holds.py:131
- §2.1 ¶3 — revise — ambiguity — paginated `/cbb/reservations` is NOT ownership-filtered; a TC sees every centre's holds — routes/reads.py:241-259
- §2.3 ¶1 — revise — ambiguity — out-of-range/non-integer/empty `limit`/`offset` is `ERR_VALIDATION_FAILED` (422), never clamped, validated before other query params; creation-sequence is the `created_at` tie-break on every list (load-bearing under a frozen clock) — middleware.py:167-187, store.py:171-173
- §2.3 ¶2 — revise — ambiguity — `offset` past end is a 200 empty page; filters conjunctive; undeclared enum filter value is 422 not an empty page; empty filter value treated as absent; unknown query params ignored — routes/reads.py:217-274, middleware.py:218-226
- §2.9 rung 3 — revise — ambiguity — rung-3/rung-6 interaction: the seven enrollment-addressed checks compare path id to `X-User-ID` with no lookup (403 even for a nonexistent enrollment) while account-/invoice-addressed forms load the row and fall through to 404 — services.py:193-217
- §2.9 rung 4 — revise — **mismatch** + ambiguity — count four->five; an unresolvable reservation id falls through to `ERR_RESERVATION_NOT_FOUND` rather than 403 — services.py:218-224
- §2.9 rung 5 — revise — ambiguity — five global shape conventions: absent/empty body reads as `{}`; non-object or non-JSON-`Content-Type` payload is 422 (never 400/415); explicit `null` == absent; strict types (bool rejects `0`/`1`, integer field rejects `1.5`); undeclared body fields (incl. client-supplied `id`) ignored; timestamp latitude (lowercase `t`/`z`, space separator, omitted zone = UTC, `+/-HH:MM`/`+/-HHMM` normalized) — middleware.py:37-48,76-135, store.py:64-99, app.py:35-52
- §3.7 search ¶1 — revise — ambiguity — `required_hla_match_count` still range-validated to the closed 0–6 interval (422 outside) despite filtering nothing; `program_scope`/`patient_weight_kg` required, weight strictly positive, `min_dose` non-negative — routes/reads.py:282-285
- §3.7 search ¶2 — revise — ambiguity — projected `potency_grade` = latest `ACTIVE` listing's frozen grade, else latest listing of any status, else null (normal for `PRIVATE_DIRECTED`); creation sequence is the third ranking tie-break — routes/reads.py:296-320
- §4 preamble — insert — ambiguity — routing fallbacks decided before authentication and answer headerless requests: unmatched path -> `ERR_NOT_FOUND` (404), undeclared method -> `ERR_METHOD_NOT_ALLOWED` (405); trailing slash insignificant; no endpoint ever answers 5xx (unclassified failures surface as `ERR_VALIDATION_FAILED` 422) — app.py:19,26-33,45-52
- §5 catalogue — insert — **mismatch** — added the two missing rows `ERR_NOT_FOUND | 404` and `ERR_METHOD_NOT_ALLOWED | 405` (impl emits both; catalogue had 53 of 55 ids) — errors.py:68-70

Verified-clean in Pass 1: all 30 GET routes and their authorized-role sets diffed programmatically against the §4 table (exact match); the other 53 error->status mappings match §5; envelope shapes, `has_more`/`total_count`, object-vs-list `meta` keys, UUID ids, 3-fractional-digit ISO timestamps, the `2026-08-01T00:00:00Z` default clock, and the `QualityTest` no-`updated_at`/no-`version` exception were already uniquely pinned. Confirmed by booting the server on port 19605 and probing ~60 edge cases (server stopped afterward).

### Pass 2 — calculation/cascade layer (calc.py, services.py)
14 edits (12 ambiguity-pins, 2 mismatch-revisions; 119,182 -> 123,146 chars, 522 lines):
- §2.4 — insert — ambiguity — reconciliations of `balance_cents`/`occupied_slots`/`cumulative_excursion_minutes_30d` bump `updated_at`/`version` only when the recomputed figure differs — services.py:265,283,295
- §3.2 (unit mint) — insert — ambiguity — `storage_account_id` resolved once at mint, never backfilled when an account opens later, so such a unit is never billed or settled — services.py:125-129
- §3.1 (withdrawal) — insert — ambiguity — consent-revocation disposal also clears `quarantine_reason_code` to null — services.py:562
- §3.1 (COLLECTED->CLOSED) — insert — ambiguity — at least one unit must exist for auto-close (a rejected-collection enrollment stays `COLLECTED`); the account closes only from `ACTIVE` or `ABANDONED` — services.py:485-496
- §3.3 (score bullet 4) — insert — ambiguity — absent `post_processing_volume_ml` yields a 0.0 volume penalty, not 0.10 — calc.py:174-178
- §3.3 (score closing) — insert — ambiguity — the score is derived only when the `POST_PROCESSING` test is written and never re-derived when a later run republishes or nulls the volume — services.py:246-254
- §3.5 (quarantine cascade) — insert — ambiguity — hold cancellation hangs off the suspended listing, so a `PRIVATE_STORED` unit with no `ACTIVE` listing keeps its pending holds — services.py:415-425
- §3.5 (resolution) — insert — ambiguity — `duration_minutes` is 0 when `resolved_at` is not later than `detected_at` — calc.py:251-256
- §3.5 (benign compensation) — insert — ambiguity — a `PUBLIC_DONATION` quarantined unit with no `UNIT_QUARANTINED`-suspended listing returns to `UNAVAILABLE` — services.py:436-441
- §3.7 (release gate) — insert — ambiguity — an `INDETERMINATE` (or any non-`NON_REACTIVE`) governing panel is refused with `ERR_MATERNAL_SCREENING_INCOMPLETE`, not `..._REACTIVE` — services.py:596-599
- §3.7 (release summary) — insert — ambiguity — null/zero conventions for `confirmatory_recovery_pct`, `dose_gate_passed`, `maternal_result`, `tank_status`, `account_balance_cents` (0) and `projected_settlement_total_cents` (null) — services.py:629-651
- §3.8 (surcharge line) — insert — ambiguity — with several units on one account, units are walked `created_at` ascending and one `PREMIUM` tank suffices; a null `tank_id` contributes nothing — services.py:312-320
- §3.8 (write-off path) — **revise** — mismatch — write-off covers `ISSUED`, `PAST_DUE` and `DELINQUENT`, not `DELINQUENT` alone (§3.8 contradicted §3.9) — services.py:471-478
- §3.9 (settlement waterfall) — **revise** — mismatch — the waterfall runs on release and director disposal only; withdrawal/consent-revocation disposal posts no settlement and voids invoices instead — services.py:544-574 vs 516-541

Verified-as-already-pinned in Pass 2: all 18 calc constants and thresholds, per-line invoice rounding order, score single-rounding, the PRE_CRYO/POST_THAW three-step dose order, anniversary-vs-prorated refund keyed on `plan_term_years`, disposition-fee tiers on the pre-fee subtotal, `days_past_due`/`unused_days` calendar-date conventions, 30-day excursion window inclusivity, governing-panel selection, and the dispose/withdraw cascade step orders.

### Pass 3 — write-endpoint layer (routes/enroll.py, lab.py, clinical.py, registry.py, holds.py, tanks.py, billing.py, ops.py)
31 Edit operations covering 36 pinned behaviors (35 ambiguity-pins, 1 mismatch-revision; 123,146 -> 136,359 chars, 522 lines):
- §3.1 — insert — both consent flags optional, default `false`; minted row's initial `lifecycle_status`/`consent_status`/`consent_version` 0/`consent_amendment_count` 0 plus null `consent_signed_at` and `withdrawal_reason_code` — enroll.py:25-44
- §3.1 — insert — `consent_document_hash` validated then discarded; omitted/explicitly-null flags leave stored values untouched rather than resetting to false; only the first signature moves `CONSENT_PENDING -> ACTIVE` — enroll.py:52-71
- §3.1 — insert — `amendment_reason_code` validated then discarded; order is terminal-lifecycle -> consent axis -> budget, so amending a never-signed consent is `ERR_INVALID_ENROLLMENT_STATE`, not `ERR_CONSENT_AMENDMENT_LIMIT` — enroll.py:83-91
- §3.1 — insert — withdrawal's `COLLECTED` guard reports `ERR_INVALID_UNIT_STATE`, evaluated only after the enrollment's own lifecycle rung — enroll.py:109-114
- §3.2 — insert — dispatch examines the enrollment axis before kit population and consent after both, so a second dispatch reports `ERR_INVALID_ENROLLMENT_STATE` — lab.py:40-44
- §3.2 — insert — collection examines the kit axis before the enrollment axis, then consent, then `ERR_KIT_EXPIRED` — lab.py:79-85
- §3.2 — insert — receipt answers **201** because it mints the unit; full minted row incl. five null characterization fields and the once-only account walk — lab.py:136,139-175
- §3.3 — insert — the live-run rung fires first as `ERR_INVALID_RUN_STATE`; availability axis before processing axis, both `ERR_INVALID_UNIT_STATE` — clinical.py:123-127
- §3.3 — insert — `tnc_millions`, `cd34_thousands`, `pre_tnc_millions`, `post_tnc_millions` are strict integers (`1.5` -> `ERR_VALIDATION_FAILED`); no unit-axis rung guards a test — clinical.py:193-198,203
- §3.3 — insert — `reservation_id` resolved as a body FK but is not a field of the test and never appears in its representation — clinical.py:198,220-250
- §3.3 — insert — duplicate `POST_PROCESSING` refused `ERR_INVALID_UNIT_STATE` after FK resolution; confirmatory linkage needs a truthy `post_processing_tnc_millions` and writes only `confirmatory_test_id` + `post_thaw_dose_x1e7_per_kg` — clinical.py:203,214-250
- §3.4 — insert — `cmv_result` optional and stored as null; `nat_confirmed` defaults false; filing carries no state rung whatever the enrollment's axes — clinical.py:57-59
- §3.4 — insert — amending an `INVALID`/`EXPIRED` panel freezes `status` and `overall_result` but still re-derives `reactive_marker_codes` and `valid_until`; an amendment restating nothing is accepted and still counts as a mutation — clinical.py:89-104
- §3.4 — insert — determination requires `eligibility_status == PENDING`, processing axis before eligibility axis, both `ERR_INVALID_UNIT_STATE` — clinical.py:266-268
- §3.4 — insert — nothing is minted; the response is the updated unit row at HTTP 200 — clinical.py:302
- §3.5 — insert — duplicate `tank_code` is a shape failure (`ERR_VALIDATION_FAILED`, before any write); a one-sided maintenance window is accepted and simply inert — tanks.py:24-28
- §3.5 — insert — cryopreservation requires `availability_status == UNAVAILABLE` with the processing axis checked first, and re-reconciles both `occupied_slots` and `cumulative_excursion_minutes_30d` — clinical.py:318-320,347-353
- §3.5 — insert — a reading persists no row, answers **200** returning the **tank** (not the excursion), and only `ONLINE`/`MAINTENANCE` move to `ALARM` while the quarantine cascade fires regardless — tanks.py:53-84
- §3.5 — insert — acknowledgement writes nothing outside the excursion row — tanks.py:97-101
- §3.5 — insert — `peak_temperature_c` required on resolution and overwrites the tracked peak unconditionally, even when cooler; the tank moves only out of `ALARM` while the unit/listing halves run regardless — tanks.py:109-136
- §3.6 — insert — publication's real adjudication order (version -> both unit axes -> consent/panel/sterility/eligibility/quality -> program type -> duplicate listing -> account), so a `PRIVATE_STORED` private unit fails at the availability axis, not `ERR_PROGRAM_TYPE_MISMATCH` — registry.py:28-73
- §3.6 — insert — resume declares no body fields (absent/empty/populated body all fine) and reports `ERR_UNIT_NOT_ELIGIBLE` only after the listing-state pair — registry.py:122-131
- §3.7 — insert — the created hold row's seven null fields, `PENDING_CONFIRMATORY` start, `PRE_CRYO` variant, and the unit `version` bump — holds.py:63-85
- §3.7 — insert — confirmation order is reservation state -> unit availability -> eligibility -> 72-hour window, so a stale hold on a quarantined unit never reports the window error — holds.py:97-106
- §3.7 — insert — decline's `reason_code` bounded 1–60 chars, scope strictly the one row — holds.py:133-141
- §3.7 — insert — cancel's `reason_code` likewise bounded 1–60 chars — holds.py:150-170
- §3.7 — insert — release leaves `processing_status` untouched (ships frozen) and leaves `settlement_total_cents` null when the unit carries no account — holds.py:187-203
- §3.8 — insert — account creation's initial row values, and that no consent or lifecycle rung guards it — billing.py:28-47
- §3.8 — insert — no account-status rung guards issuance (any delinquency rung, `CLOSED`/`ABANDONED` included); `stage_advanced_at` null until a nightly advance — billing.py:57-84
- §3.8 — insert — `amount_cents` strictly positive integer; `payment_reference` validated then discarded; invoice-state checked **before** the residual test; response body is the invoice, not the account — billing.py:95-121
- §3.9 — insert — the `ABANDONED_NONPAYMENT` guard reports `ERR_INVALID_UNIT_STATE` (not a fiscal code), runs after the availability rung, and refuses an account-less unit — holds.py:214-220
- §3.9 — insert — the nightly batch's seven families execute in a pinned order (kits -> panels -> holds -> excursions -> maintenance -> invoices -> accounts, unit flagging inside the last), load-bearing because the account ladder consumes invoices the invoice ladder just advanced — ops.py:38-184
- §3.9 — insert — every batch expiry comparison is **strict** (a stamp exactly on the clock survives); kits, panels, holds, excursions and tanks are walked `created_at` ascending with creation sequence as tie-break — ops.py:39-97
- §3.9 — revise — clock endpoint: PlatformAdmin-only, the sole route outside `/cbb`, `current_utc` required RFC 3339 string, clock keeps the normalized instant but the 200 response echoes the client's string **verbatim** (the one un-normalized timestamp in the API) — ops.py:188-197
- §4 preamble — insert — the six optional free-text notes (`note` x2, `decision_note`, `suspension_note`, `acknowledgement_note`, `release_note`) are validated then discarded, empty string allowed, all bounded at 500 chars except the collection-rejection `note`, which has no upper bound — lab.py:180, holds.py:178/211, clinical.py:261, registry.py:97, tanks.py:91
- §4 endpoint table — revise — **mismatch** — the `POST /cbb/storage-accounts` row claimed "for a consented enrollment"; the impl performs no consent or lifecycle check, so the row now reads "against an enrollment ... no consent or lifecycle precondition applies" — billing.py:16-47

Pass 3 discarded candidates (impl exhibits no distinguishable behavior, so no prose invented): `volume_reduction_pct` nulling when `pre_volume_ml` is absent, the publication quality floor with absent counts, and `suspend_listing`'s unconditional `touch(unit)`.

### Orchestrator verification (Step 9)
- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` -> **differs** (the no-op-scan failure mode did not occur); `diff` = 124 changed lines; 518 -> 522 lines, 112,654 -> 136,359 chars.
- `tail -3 PRD_COMPLETED.md` ends on the complete §5 row `| ERR_METHOD_NOT_ALLOWED | 405 |` — no truncation.
- `find` confirms **0** `.py` files under `workspace/implementation/`, `test_suite/` or `test_helpers/` were modified after the green sweep (22:43), so the 8x 179/179 result set remains valid for the delivered artifacts; Steps 8 and 9 edited PRD documents only.

## Pipeline complete
All nine steps finished. Final artifacts: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/` (9 modules), `test_suite/` (conftest + 20 modules, 179 tests), `workspace/PRD.md`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`, `workspace/implementation/` (3,338 lines + `results.{1..8}.json`, all 179/179).

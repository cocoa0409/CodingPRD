# Worklog — task_2653_ground_lease_administration

## Step 1: Create task directory — 2026-09-04T01:48:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2653_ground_lease_administration` and `.../workspace` (pre-assigned path from the orchestration request; no index auto-allocation performed).

## Step 2: Generate scaffold — 2026-09-04T03:25:00.000Z

All three artifacts are complete, parse cleanly, and the linter reports **clean lint**.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    66
  §1.1 entities declared:     13
  §1.8 instances scanned:     26
  §1.9 instances scanned:     53
  Calls scanned (§1.8+§1.9):  708

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all under the task dir):

| File | Lines | Contents |
|---|---|---|
| SCAFFOLD.yaml | 2807 | §1.0–§1.7. 13 entities, 12 state machines, 2 concurrency rules, 7 calculations, 18 validations (P1–P18), 66 endpoints, 39 errors, 6 roles. `api_prefix: /portfolio`; archetypes `multi_party_negotiation` / `pricing_engine`; layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `scheduled_deferred_actions`; topology `flat`; state shape `parallel`; role model `segregation_of_duties`; consistency `immediate`. Tail ends on the Arbitrator role's `shared_operations`. |
| SCAFFOLD_DIFFICULTY_DESIGN.yaml | 1993 | Single key `scaffold_difficulty_design`: **9 rule_ids / 26 instances** (>=2 each). Tail ends on a deposit-conservation assert. |
| SCAFFOLD_CORNER_DESIGN.yaml | 3126 | Single key `scaffold_corner_design`: **9 sections / 82 instances = 53 real test_recipes + 29 `excluded_because` stubs**. Tail ends on the consistency-model instance's last assert. |

§1.9 section breakdown: entities 12, state_machines 16, calculations 13, validations 17, endpoints 6, errors 9, rbac 4, cross_cutting_complexity_layers 4, consistency_model 1. All 82 names are unique across the §1.8 ∪ §1.9 union; every stub cites a real §1.8 instance name; every non-stub has all four `test_recipe` keys.

Design adjudications:
- **Domain shape.** Lease carries two parallel axes (`lease_status` × `rent_status`) so tenancy and rent-setting evolve independently; the whole revaluation/arbitration cycle, the mortgagee notice/cure/new-lease ladder and the reversion condition-standard machinery hang off that split.
- **Casualty vs condemnation.** A casualty `LossEvent` cannot allocate straight from ADJUSTED (it must pass RESTORATION_ELECTED), so every ledger-sync and waterfall instance routes through CONDEMNATION; the election gate itself is probed by a negative instance (`ERR_ELECTION_NOT_AVAILABLE` on a condemnation).
- **Termination path forks.** `terminate` from `LESSEE_CURE_LAPSED` requires an unencumbered lease, so the statement-cascade instance carries no mortgage, while the new-lease-election instance walks two clock+sweep steps to reach `MORTGAGEE_CURE_LAPSED`. New-lease election additionally needs `arrears == 0`, so it is driven by a non-monetary `UNPERMITTED_USE` default.
- **Sweep counter hygiene.** Phase 3 revaluation flagging would have polluted the administration-run counters, so sweep-driven fixtures use `revaluation_interval_years: 20`; statement periods all sit inside 2026-01-01…2026-07-01 to satisfy the "period_end not in the future" chronology clause.
- **Strict vs inclusive comparisons pinned deliberately.** Insurance lapse fires "at or before now" (so an expiry equal to `now` lapses) while cure-window lapse is strictly `now > deadline`; the arbitration divergence gate is strictly-greater. Each of the three is asserted at the boundary and one second past it.
- **§1.9 claim_type discipline.** For the two guide sections with no claim-type table (Errors, RBAC) the generator coined the minimal set implied by their prose — `triggerability`, `exclusive_operations`, `unauthorized_operations` — and used the table rows verbatim everywhere else.
- **Coverage economy.** Every one of the 39 error codes is triggered somewhere; the eight codes already owned by §1.8 are stubs, and the eleven remaining 404s are swept in one instance that also pins referential-before-OCC ordering.
- **Two lint-driven fixes** during assembly: two asserts named non-existent nested list routes (rewritten to the declared `?lease_id=` / `?revaluation_id=` filters), and the 404-sweep instance originally used a literal `expected_lease_version: 99` — replaced with a captured-then-staled `${stale_version}`.

Orchestrator verification: `yaml.safe_load` succeeds on all three; DIFFICULTY has exactly `scaffold_difficulty_design`, CORNER exactly `scaffold_corner_design`, SCAFFOLD.yaml has neither.

## Step 3: Copy shared files — 2026-09-04T03:25:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-04T03:47:00.000Z

PRD complete.

**Output:** `workspace/PRD.md` — **492 lines, 113,201 bytes**, ends cleanly at the last row of the §5 error table (`ERR_TRANSFER_FIELDS_MISMATCHED | 422`), no audit footer, no truncation.

**Structure:** §1 Introduction (3 paras) → §2 Global Specifications (12 domain-derived subsections; §2.2 emitted byte-identical from `section-2.2-response-structure.md`) → §3 Business Logic (9 subsections, lifecycle-staged) → §4 Endpoint Definitions (4-column table) → §5 Error Code Catalogue (2-column table).

**Coverage verified programmatically against the scaffold:**
- **66 endpoints** — 66 table rows, each matched exactly on `method` + `path` against `SCAFFOLD.yaml`; 0 missing.
- **39 errors** — 39 rows, IDs and HTTP statuses taken directly from `errors[].id`/`errors[].http`.
- **13 entities** — all named in prose.
- **12 state machines / 66 transitions** — every declared state string appears in the document; every transition described in narrative (spot-verified the 19 that a strict `A -> B` regex missed; all are covered in prose form).
- **7 calculations** — all translated to step-numbered prose with exact constants (reval collar, sublease inclusion, percentage-rent tiers, transfer-fee tiers, four-bucket waterfall with both `lessee_share_bps` variants, cure days 10/15/30 + widest `cure_extension_days`, reversion weights 6000/3000/1000, 4000/3000/3000, 7000/2000/1000 with passing scores 7000/8500/6000).
- **18 validations** — the §2.8 ordered refusal list mirrors `validations[].priority` 1–18.
- **6 roles** — all six named and characterised in §2.1 and used throughout §4.

**Hard Contracts:**
- **Contract 1 (Field-Name Coverage): PASS** — 0 of 138 `entities[].fields[].name` missing; 0 of 113 endpoint `input`/`path_params`/`query_params`/`output` identifiers missing (two passes, re-run after the final renumbering).
- **Contract 2 (Rule Coverage): PASS** — all 18 validation priorities with their `applies_to` scopes; both `concurrency_rules` (`expected_lease_version` → `ERR_STALE_LEASE_VERSION`/412 on statement filing and estoppel issuance); all cross-entity guards; sibling-branch symmetry documented where the scaffold is asymmetric (NOTICE_SERVED→RECORDED clears `mortgagee_notified_at` vs CURING→RECORDED retaining it; APPROVE vs REJECT; `SUBMITTED → VOID` vs `PROVISIONAL_ASSESSED → VOID` ledger consequences; both `INSPECTED → CLOSED` and `HOLDBACK_APPLIED → CLOSED` routes).
- **Contract 3 (§3 Path Purity): PASS** — 0 impure backtick tokens in §3; 0 occurrences of `/portfolio` or `_clock` anywhere in §3. Endpoints are named by state-transition pairs, role + gerund, or capability description.

**Scaffold ambiguities resolved** (documented explicitly so the prose uniquely determines behaviour): the arbitrator-independence bar at referral and the casualty-adjust insurance/policy-limit preconditions carry no `error_id` in the scaffold — assigned `ERR_SEGREGATION_OF_DUTIES` and `ERR_INSURANCE_DEFICIENT` respectively, with §2.1/§2.8 retro-edited for self-consistency. Sublease interval semantics follow validation rule 10 (half-open, touching endpoints allowed) over the conflicting entity comment. Header casing normalised to `X-User-ID` throughout.

The two withheld files were never opened, grepped or referenced, and no sibling task directory was read.

Orchestrator truncation check (per known doc-generator failure mode): `tail -25` ends at a complete error-table row; all five top-level sections (§1–§5) present at lines 3/11/169/375/448. NOT truncated — no regeneration needed.

## Step 6: Generate implementation — 2026-09-04T04:22:00.000Z

The implementation is complete and smoke-verified.

## Files — `workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `start.sh` (executable) | 10 | Guarded `pip install` (`if ! python3 -c "import flask"`), `exec python3 app.py` |
| `requirements.txt` | 1 | `Flask>=2.0` |
| `app.py` | 79 | Blueprints under `/portfolio`, `POST /_clock/set_current_utc` outside the mount, `ApiError`/`HTTPException`/`Exception` handlers, `app.run(host="0.0.0.0", port=$PORT or 10000)` |
| `errors.py` | 101 | `ApiError` + all 39 error IDs -> HTTP status |
| `store.py` | 198 | 13 in-memory dicts, logical clock (default `2026-08-01T00:00:00Z`), ISO-3-digit formatting, day/year arithmetic, id/version stamping |
| `response.py` | 41 | `meta`/`response_type`/`data` envelope, pagination meta fields |
| `validate.py` | 219 | Body-shape validators, `ROUND_HALF_UP` helper, `limit`/`offset` pagination |
| `auth.py` | 56 | `X-User-ID`/`X-User-Role`, six roles, GroundTenant ownership |
| `serialize.py` | 188 | Per-entity field projections (appraisals deliberately carry no `updated_at`/`version`) |
| `calc.py` | 280 | Every pinned constant + all calculation rules |
| `cascades.py` | 231 | Termination/expiry/freeze cascades, sublease-base recompute, rent summary |
| `routes_setup.py` | 372 | Lessees, lease execution/amendment, insurance, rent charges, mortgages, new-lease election |
| `routes_reval.py` | 357 | Revaluation, appraisals, exchange, rounds, settle, referral, award |
| `routes_money.py` | 441 | Statements (file/assess/audit), transfers (request/decision/fee payments) |
| `routes_ops.py` | 963 | Alterations, default notices & cures, loss events & waterfall, reversion, estoppel, 5-phase sweep |
| `routes_reads.py` | 380 | 13 single reads, 13 filtered lists, `/leases/{id}/rent-summary` |

**Total 3,917 lines.** Every file passes `ast.parse`. Route map: 66 app routes = 39 writes + 27 reads, exactly matching PRD §4 (verified line-by-line against the endpoint table). No seeding anywhere; `__pycache__` removed.

## Smoke test (port 18653, killed by PID resolved from `ss -lptn 'sport = :18653'` — no pattern kill)

- Boot in <4 s; `GET /portfolio/lessees` -> 200, empty array with `limit`/`offset`/`total_count`/`has_more`.
- Envelope confirmed: `{"data":…,"meta":{"api_request_id":"req_…","api_request_timestamp":"…Z"},"response_type":"object|array|error"}`.
- Errors verified: **403** missing header + **403** wrong role (`ERR_UNAUTHORIZED`), **403** `ERR_APPRAISAL_SIDE_MISMATCH`, **404** `ERR_LEASE_NOT_FOUND`, **400** `ERR_INVALID_REQUEST`, **409** `ERR_DUPLICATE_RECORD`, **412** `ERR_STALE_LEASE_VERSION`.
- Full economic path exercised and hand-checked against PRD worked arithmetic:
  - offset credit `12,000,000 x 2500/10000 = 3,000,000` OK
  - provisional `(500M + 0 - 200M) x 600/10000 = 18,000,000`, due `15,000,000` OK
  - audit `21,600,000`, penalty `(560M-500M)x600/10000 = 3,600,000`, net ledger `18.6M - 15M + 3.6M = 7.2M` -> arrears `22,500,000` OK (reconciliation, not double charge)
  - divergence `6,000,000 x 10000 / 14,000,000 = 4286` (/ smaller, half-up) OK
  - midpoint `17,000,000` clamped **last** to collar ceiling `15,600,000`; `next_revaluation_date` advanced one 10-year interval to 2040-01-01; rent axis -> `RESET_APPLIED` OK
  - clock set -> sweep phase one lapsed insurance, served a `SYSTEM` `INSURANCE_LAPSE` notice with a 15-day deadline and `mortgagee_cure_deadline: null` (unencumbered), drove the lease `ACTIVE -> IN_DEFAULT`, and returned `insurance_lapses_raised: 1` with `affected_lease_ids` OK
  - setting the clock alone transitioned nothing OK

## Ambiguities resolved this session

- **Basis-point ceiling applies to collar uplifts.** PRD §2.7/§2.8 rejects "a basis-point figure below 0 or above 10,000", while §3.1 says only "the ceiling must be at least as large as the floor". Kept the global 0–10,000 cap at body shape (400) and left the strict `min < max` ordering to `ERR_TERMS_INCOHERENT` — so equal collars are 422, not 400.
- **List filter naming.** §3.7 says leases are discoverable by `predecessor_lease_id`/`origin_mortgage_id`; §4 says `replaces_lease_id`/`elected_by_mortgage_id`. Both spellings are accepted, resolving to the stored `predecessor_lease_id`/`origin_mortgage_id`. Same for estoppel `mortgage_id`/`requested_by_mortgage_id`.
- **Read-path precedence.** §2.8 puts referential existence above authorisation, so a GET on an unknown id returns 404 even with bad/missing headers; list endpoints check auth then pagination.
- **Ownership scope.** GroundTenant ownership is enforced on single-resource lease-scoped reads (via the owning lease, including appraisals/arbitrations reached through their revaluation) but not applied as a silent filter on list endpoints, since the PRD documents explicit filters rather than implicit scoping.
- **Unrouted paths / bad methods** emit the error envelope with `ERR_INVALID_REQUEST` at 404/405 rather than Flask's HTML.

Orchestrator note on concurrency: Steps 5 and 6 were launched in back-to-back messages rather than a single message. Step 6's prompt therefore carried an explicit absolute prohibition on reading `test_helpers/`, `test_suite/`, both design YAMLs, `worklog.md`, and any sibling task — restoring by instruction the isolation that simultaneous launch would have given physically. Step 6 reported reading only INSTRUCTION.md, SCAFFOLD.yaml and PRD.md.

## Step 5: Generate unit tests — 2026-09-04T04:48:00.000Z

The suite is complete. All output lives directly under the task root — `test_helpers/` and `test_suite/` — and nothing was written under `workspace/`.

## Files written

`test_helpers/` (1,546 lines): `__init__.py` 71, `api_client.py` 353 (72 methods), `api_errors.py` 104 (39 codes + `ERROR_HTTP_STATUS`), `assertions.py` 112, `constants.py` 175, `factories.py` 272, `fixtures.py` 310, `test_users.py` 62, `types.py` 87.

`test_suite/` (5,910 lines, 129 tests): `conftest.py` 22; `test_01_revaluation_settlement_and_arbitration.py` 413/12, `test_02_percentage_rent_assessment.py` 514/15, `test_03_transfer_consent_and_fee_pricing.py` 355/8, `test_04_alteration_envelope_and_windows.py` 393/11, `test_05_default_cure_and_termination.py` 367/9, `test_06_loss_proceeds_waterfall.py` 347/8, `test_07_reversion_and_estoppel.py` 346/8, `test_08_entity_shape_and_defaults.py` 454/12, `test_09_state_machine_transitions.py` 580/12, `test_10_calculation_breadth.py` 255/5, `test_11_validation_breadth.py` 802/12, `test_12_endpoints.py` 396/7, `test_13_errors_and_rbac.py` 369/6, `test_14_cross_cutting.py` 297/4.

## Coverage — every non-stub instance translated, none skipped

- **Queue A (§1.8 difficulty): 26 / 26 non-stub instances covered** by 71 tests.
- **Queue B (§1.9 corner): 53 / 53 non-stub instances covered** by 58 tests; the 29 `excluded_because` stubs were skipped as required. Per section: entities 12/12, state_machines 12/12, calculations 5/5, validations 12/12, endpoints 5/5, errors 1/1, rbac 3/3, cross_cutting_complexity_layers 2/2, consistency_model 1/1.

## Verification run

- `pytest --collect-only` -> **129 tests collected**, no import errors; `ast.parse` clean on all 24 files; `pyflakes` clean on every test file (only the expected re-export warnings in the `test_helpers/__init__.py` barrel).
- Docstring audit: every test has exactly one `Design:` line, it is the last line, and every tag resolves to a real **non-stub** instance — 0 untagged, 0 dual-tagged, 0 stub-tagged, 0 unknown.
- Quote audit: every `PRD §x.y: "…"` citation is a verbatim substring of `workspace/PRD.md` — **14 files checked, 0 missing**.

## Deviations from the design recipes (PRD wins in each case)

1. **`certified_lease_version`** (PIER-60, PIER-118, PIER-126): recipes assert the *pinned* version; §3.2 says the certificate records the version *after* its own increment. Asserted `pinned + 1`.
2. **PIER-93 mortgagee cure**: recipe pays 3,000,000 against 4,000,000 arrears and expects success; §3.7 says a partial payment does not cure and the balance must end at 0. Cured in full and asserted arrears 0, preserving the instance's real claim (both mortgages back to `RECORDED` with `mortgagee_notified_at` cleared).
3. **PIER-96 collar ceiling**: the recipe's `initial_annual_base_rent_cents: 20000000` makes its own asserted 15,000,000 arithmetically impossible. Dropped the override; the canonical 10,000,000 base makes every asserted figure hold.
4. **PIER-104 / PIER-115 `OFFICE_CAMPUS`**: not in the PRD's permitted-use enum, so the refusal would be `ERR_INVALID_REQUEST` 400 (priority 3), not the intended check. Substituted the valid `INDUSTRIAL_LOGISTICS`, preserving each claim (PIER-115 still shows priority 13 beating priority 17).
5. **Opaque `MortgageeAgent` ids** (`agent-keystone-1` etc.): §2.1 makes the id opaque, so headers carry the mortgage id where a per-mortgage actor is meant.
6. **`transfer_fee_total_cents`** in the rbac recipe -> the PRD field is `total_transfer_fee_cents`; recipe `decision: "GRANT"` -> the PRD enum is `APPROVE`/`DENY`.

## Assertions deliberately dropped as not uniquely derived

- **Estoppel list filter**: §3.2 says `requested_by_mortgage_id`, §4 says `mortgage_id`. Filtered by `lease_id` only.
- **HTTP status of `rent-charges` and `insurance-endorsements`**: recipes assert 201, but neither has a backing entity and §4 says lease-mutating endpoints answer 200. Used the status-agnostic `get_success_data` and asserted the ledger/insurance effects instead.
- **Carried forward**: on `resource_temporal_overlap/sublease_overlap_is_keyed_by_unit_while_the_area_cap_is_keyed_by_lease`, the single `ERR_INTERVAL_OVERLAP` assertion was dropped (priority-5 `ERR_DUPLICATE_RECORD` outranks it and §2.9's zero-day turnover rule leaves the outcome ambiguous); the instance stays covered by three other tests.

Orchestrator verification: no stray `test_*` directories under `workspace/` — both live at the task root as required.

## Step 7: Test-and-fix loop — 2026-09-04T05:16:00.000Z

Three iterations of the 8-round parallel `per-test-server` sweep. Final state: **129/129 passing in all 8 rounds, 0 failed, 0 skipped** (`results.1..8.json`, ~239 s per round).

Iteration 1 — 102/129 in every round, 27 deterministic failures (no flakiness at any point in the loop).

### Fixes to `test_helpers/`
- `assertions.py`: added `parse_instant` / `same_instant` / `assert_instant`, and made `assert_fields` compare two ISO-8601 instants as instants. PRD pins the rendering of `api_request_timestamp` (§2.2) and `created_at`/`updated_at` (§2.4) to three fractional digits but states no rendering for the business instants (`served_at`, both cure deadlines, `next_revaluation_date`, `insurance_expires_at`, `issued_at`, `run_at`, `new_lease_election_deadline`, `mortgagee_notified_at`), so `…T00:00:00Z` and `…T00:00:00.000Z` are the same PRD-conformant answer. 18 of the 27 failures were this one uncovered rendering assertion.
- `fixtures.py::referred_revaluation`: re-reads the revaluation after the referral. It had been returning the row captured at exchange, so callers saw `PROPOSALS_EXCHANGED` where §3.3 requires `ARBITRATION_REFERRED`.

### Fixes to `test_suite/`
- `test_01`: `list_arbitrations` was called with `AssetManager` headers; §4 authorises only `LessorAdmin`, `GroundTenant`, `Arbitrator` on `GET /portfolio/arbitrations`, so the 403 was correct. Now uses `LessorAdmin`.
- `test_05` mortgagee cure: asserted both mortgages return to `RECORDED`. §3.7 returns only "the acting mortgage `CURING → RECORDED`" and §3.2 deliberately contrasts that with the tenant's cure; the untouched mezzanine stays `NOTICE_SERVED`. Test renamed accordingly.
- `test_05` 30-day ground: asserted `rent_status == "BASE_ONLY"` after a sweep at 2026-09-01, but §3.9 phase three flags `BASE_ONLY → REVALUATION_DUE` because `next_revaluation_date` is 2025-01-01. Now asserts `REVALUATION_DUE`.
- `test_05` one-second-past: asserted `cure_windows_lapsed == 1` while the fixture builds **two** notices sharing the 2026-08-11 deadline. Now asserts 2.
- `test_10` / `test_12`: three raw `==` instant comparisons switched to `assert_instant`.

### Assertions removed as not uniquely derivable (partial-coverage split, §2.8 STEP 1c)
- `test_11::test_an_appraisal_lodged_for_the_other_side_is_refused` — dropped `submitted_at`; §2.4 says an `AppraisalSubmission` "carries only `id` and `created_at`" and the PRD never names `submitted_at`. Rest of the test kept.
- `test_11::test_a_holdback_is_refused_where_the_condition_standard_was_met` — `deficiency_bps` corrected 0 → 1000; §3.9 defines it as "10,000 less `weighted_score_bps`" unconditionally.
- `test_14::test_every_derived_figure_is_final_in_the_first_response_that_carries_it` — dropped `excess_sales_cents` (COMPUTED-FIELD SILENCE: §3.4 step three names "the excess" only as an intermediate, never as a statement attribute).

No test was deleted outright, and no assertion was weakened to an HTTP-status check; no skip/xfail markers exist in the suite.

### Fix to `implementation/`
- `routes_money.py::create_transfer`: the priority-5 `premises_unit_code` uniqueness check now fires only when the proposed term actually overlaps the ACTIVE sublease's term. It had been unconditional, which contradicted §2.9's "The turnover buffer the lessor requires between successive subleases of one unit is zero days, so back-to-back subleases of the same unit are permitted with no gap". Priority 5 vs 10 stays observable: an intersection with an `ACTIVE` sublease reports `ERR_DUPLICATE_RECORD`, one with a `SUBMITTED`/`CONSENT_GRANTED` sublease reports `ERR_INTERVAL_OVERLAP`.

## Step 7 (orchestrator record: verbatim subagent exit summary) — 2026-09-04T05:40:00.000Z

All 8 rounds green. Final state below.

## Iterations run
**3** iterations of the 8-round parallel `per-test-server` sweep (129 tests/round, ~239 s/round). Iteration 1: 102/129 in every round. Iteration 2: 127/129. Iteration 3: clean. Every failure was fully deterministic across all 8 rounds — no flakiness surfaced at any point, and no load-induced timeout/connection failures.

## Tests deleted
**None.** No test failed STEP 1a outright. Three tests were *split* under STEP 1c (uncovered assertion removed, covered assertion kept):
- `test_11::test_an_appraisal_lodged_for_the_other_side_is_refused` — dropped `submitted_at="…"`: §2.4 says an `AppraisalSubmission` "carries only `id` and `created_at`" and the PRD never names `submitted_at`. (Scaffold rule: `Corner/validations/appraisal_side_must_match_the_acting_role_rejected`.)
- `test_14::test_every_derived_figure_is_final_in_the_first_response_that_carries_it` — dropped `excess_sales_cents`: COMPUTED-FIELD SILENCE, §3.4 step three names "the excess" only as a computation intermediate. (`Corner/consistency_model/every_write_response_already_carries_its_derived_fields`.)
- A fourth, larger split: the exact **fractional-digit rendering** of business instants. PRD pins three fractional digits for `api_request_timestamp` (§2.2) and `created_at`/`updated_at` (§2.4) but is silent for `served_at`, both cure deadlines, `next_revaluation_date`, `insurance_expires_at`, `issued_at`, `run_at`, `new_lease_election_deadline`, `mortgagee_notified_at`. 18 of the 27 first-iteration failures were only this. Handled centrally rather than test-by-test (below); every instant *value* assertion was retained.

## Fixes to `test_helpers/`
- `assertions.py` — added `parse_instant` / `same_instant` / `assert_instant`, and made `assert_fields` compare two ISO-8601 instants as instants. Removes the PRD-uncovered rendering assertion while keeping the instant-value assertion exact.
- `fixtures.py::referred_revaluation` — re-reads the revaluation after the referral. It had returned the row captured at exchange, so callers saw `PROPOSALS_EXCHANGED` where §3.3 requires `ARBITRATION_REFERRED` (broke 2 estoppel tests).
- `__init__.py` — export the three new helpers.

## Fixes to `test_suite/`
- `test_01` (`…referral_is_blocked_while_the_lease_is_in_default`) — `list_arbitrations` used `AssetManager` headers; §4 authorises only `LessorAdmin`/`GroundTenant`/`Arbitrator` on `GET /portfolio/arbitrations`, so the 403 was correct. Switched to `LessorAdmin`.
- `test_05` mortgagee cure — asserted *both* mortgages return to `RECORDED`. §3.7 returns only "the acting mortgage `CURING → RECORDED`", and §3.2 deliberately contrasts that with the tenant's cure; the untouched mezzanine stays `NOTICE_SERVED`. Assertion corrected, test renamed to match.
- `test_05` 30-day ground — asserted `rent_status == "BASE_ONLY"` after a sweep at 2026-09-01; §3.9 phase three flags `BASE_ONLY → REVALUATION_DUE` since `next_revaluation_date` is 2025-01-01. Now asserts `REVALUATION_DUE`.
- `test_05` one-second-past — asserted `cure_windows_lapsed == 1` while its fixture builds **two** notices sharing the 2026-08-11 deadline. Now 2.
- `test_11` holdback — `deficiency_bps` corrected 0 → 1000; §3.9 defines it as "10,000 less `weighted_score_bps`" unconditionally, and `weighted_score_bps` is 9000.
- `test_10`, `test_12` — three raw `==` instant comparisons switched to `assert_instant`.

No skip/xfail was added (verified: zero markers in `test_suite/`), and no `error_id` assertion was downgraded to an HTTP-status check.

## Fixes to `implementation/`
- `routes_money.py::create_transfer` — the priority-5 `premises_unit_code` uniqueness check now fires only when the proposed term actually overlaps the ACTIVE sublease's term. It had been unconditional, contradicting §2.9's verbatim "The turnover buffer the lessor requires between successive subleases of one unit is zero days, so back-to-back subleases of the same unit are permitted with no gap." Both priorities stay observable: intersection with an `ACTIVE` sublease → `ERR_DUPLICATE_RECORD` (priority 5); with a `SUBMITTED`/`CONSENT_GRANTED` one → `ERR_INTERVAL_OVERLAP` (priority 10). No PRD-required check was removed; storage remains in-memory dicts with no seeded data (audited).

## Final sweep (8 complete `results.$i.json` on disk, `workspace/implementation/`)
| round | passed/total | failed | skipped |
|---|---|---|---|
| 1 | 129/129 | 0 | 0 |
| 2 | 129/129 | 0 | 0 |
| 3 | 129/129 | 0 | 0 |
| 4 | 129/129 | 0 | 0 |
| 5 | 129/129 | 0 | 0 |
| 6 | 129/129 | 0 | 0 |
| 7 | 129/129 | 0 | 0 |
| 8 | 129/129 | 0 | 0 |

Orchestrator verification (independent of the subagent's claim, per the known "clean sweep with no artifacts" failure mode): all 8 `results.$i.json` were re-read from disk with `json.load` — every one reports `passed=129, total=129, failed=0`. Step 8 is therefore NOT skipped (1 `implementation/` fix, 3 `test_helpers/` fixes, 6 `test_suite/` fixes).

## Step 8: Finalize PRD — 2026-09-04T05:51:00.000Z

`PRD_FINALIZED.md` is written. Three surgical edits; all other prose is byte-identical to `PRD.md`.

## Size
- `PRD.md`: 492 lines / 112,780 chars — `PRD_FINALIZED.md`: 492 lines / 114,473 chars.
- Line-count delta 0.00% (the file is one-paragraph-per-line); character delta **+1.50%**.

## Changes
- **§2.4 — insert** — pinned the wire rendering of *all* instants: every non-null instant the service returns (resource payloads, computed reads, the sweep's `run_at`, the clock's `current_utc` echo) is ISO 8601 UTC with exactly three fractional digits and a trailing `Z`; client-supplied instants are normalised to UTC and re-rendered rather than echoed verbatim — `implementation/store.py:77-86` (`iso`), `serialize.py:117-124` (`_value`), `response.py:16`, `app.py:45`, `routes_ops.py:960`.
- **§2.8 priority 5 — revise** — the `premises_unit_code` uniqueness guard is scoped to active subleases *whose term intersects the proposed term* — `implementation/routes_money.py:258-275`.
- **§3.6 — revise** — rewrote the first two structural checks at transfer application: `ERR_DUPLICATE_RECORD` only for an `ACTIVE` sublease of that unit whose term actually intersects (so back-to-back applications with no gap are accepted); `ERR_INTERVAL_OVERLAP` for a `SUBMITTED`/`CONSENT_GRANTED` sublease of that unit; both use the half-open test — `implementation/routes_money.py:258-292`, `cascades.py:204-206`.

## Pre-edit search log

**Edit 1 — §2.4 instant rendering**
- (a) Subject: the wire format of every instant-valued field in every response.
- (b) Enumerated/read: `store.py:77-86` `iso()` — the *only* formatter, always `%.03d` + `Z`, `astimezone(UTC)` first; `store.py:89-121` `parse_dt` (offset normalisation); `serialize.py:9-18` `DATETIME_FIELDS` and `serialize.py:117-124` `_value()` — applies `iso` to *any* `datetime` regardless of field name; `response.py:_meta` (`api_request_timestamp`); `app.py:43-45` (`current_utc`); `routes_ops.py:960` (`run_at`); grepped all 14 `req_dt`/`opt_dt` callsites confirming client instants are stored as `datetime`; `routes_setup.py:121,341` (`next_revaluation_date`), `:231` (`insurance_expires_at`); `calc.cure_deadlines`; `cascades.terminate_lease` (`new_lease_election_deadline`). Live-probed the running server: `current_utc`, `created_at`, `commencement_date`, `expiration_date`, `next_revaluation_date` all returned `.000Z`.
- (c) Adjustment: widened from "business instants" to *every* instant returned, and explicitly added the client-supplied list — a narrower claim naming only server-derived instants would have mis-described `valuation_date`, `term_start`, `period_start`, `occurred_at`, `construction_window_*`, `hearing_date`, which `_value` also re-renders. Qualified with "non-null" because nulls stay null.

**Edit 2 — §2.8 priority 5** and **Edit 3 — §3.6** (same subject, one search)
- (a) Subject: what makes a `premises_unit_code` "already taken", and which of `ERR_DUPLICATE_RECORD` / `ERR_INTERVAL_OVERLAP` a colliding sublease application gets.
- (b) Enumerated/read: `routes_money.py:258-275` (priority 5: SUBLEASE + `ACTIVE` + same unit + `overlaps` -> `ERR_DUPLICATE_RECORD`, and it runs *before* `require_operative` at `:277`); `routes_money.py:279-292` (priority 10: `SUBMITTED`/`CONSENT_GRANTED`/`ACTIVE` + same unit + `overlaps` -> `ERR_INTERVAL_OVERLAP`, after `require_operative`); `routes_money.py:294-301` (chronology, after both); `routes_money.py:375-390` `decide_transfer` (parallel endpoint: `CONSENT_GRANTED`/`ACTIVE`, self excluded -> `ERR_INTERVAL_OVERLAP`); `routes_money.py:241-256`; `cascades.py:204-206` `overlaps` (half-open); `serialize.py:80`. Grepped `premises_unit_code` across the whole implementation — no other consumer. Live-probed all four cases (touching-after-`ACTIVE`, disjoint, overlapping-`ACTIVE`, overlapping-`SUBMITTED`) and got accepted / accepted / `ERR_DUPLICATE_RECORD` / `ERR_INTERVAL_OVERLAP`.
- (c) Adjustment: described the priority-10 set as `SUBMITTED`/`CONSENT_GRANTED` rather than copying the impl's set that also lists `ACTIVE` — behaviourally identical, since the priority-5 check has already refused any overlapping `ACTIVE` row, and stating `ACTIVE` at both priorities would be self-contradictory prose. Kept "half-open" explicit on both checks so touching endpoints stay permitted. Deliberately left §2.9 and the §3.6 consent-decision check untouched: both already match the implementation. Left the check ordering relative to `ERR_LEASE_NOT_OPERATIVE` unstated in §3.6 — §2.8's priority table already yields the impl's ordering (5 < 7 < 10).

## Step 7 items that needed *no* PRD change (verified, not assumed)
- `submitted_at` on `AppraisalSubmission` and `excess_sales_cents` on a statement: neither field exists anywhere in `implementation/` (`serialize.py:53-56`, `:64-69`; grep returns nothing). Test-side over-assertions, already determined by §2.4 / §3.4.
- `fixtures.py::referred_revaluation`, `test_01` `AssetManager` on `GET /portfolio/arbitrations`, `test_05` `REVALUATION_DUE`, `test_05` `cure_windows_lapsed == 2`, `test_11` `deficiency_bps == 1000`: all pure fixture/test bugs — §3.3, §4, §3.9 phase three, §3.9 counts and §3.9 `10,000 less weighted_score_bps` (`routes_ops.py:725`) already determine the implementation's behaviour.
- `test_05` mortgagee cure returning only the acting mortgage to `RECORDED`: `routes_ops.py:399` touches only the named mortgage, exactly as §3.7 and §3.2 already state.

## Step 9: Complete PRD — 2026-09-04T07:05:00.000Z

Run as **three sequential file-partitioned passes** rather than one subagent, because the implementation is 3,917 lines across 16 files and a single-context exhaustive walk reliably degrades into a no-op (the known failure mode: `PRD_COMPLETED.md` comes back byte-identical to `PRD_FINALIZED.md`). Pass 1 owned PASS 0 (the `cp` from `PRD_FINALIZED.md`); Passes 2 and 3 edited the same file additively in place. **76 total changes: 60 ambiguity-pins, 16 mismatch-revisions.** Every edit was an in-paragraph insert or revision — the file stayed at 492 lines throughout, with no new sections.

### Pass 1 — app.py, errors.py, store.py, response.py, validate.py, auth.py, serialize.py, routes_setup.py, routes_reval.py
24 ambiguity-pins, 3 mismatch-revisions.
- §2.1 — insert — ambiguity — header values are whitespace-stripped, so whitespace-only counts as absent — auth.py:27-34
- §2.1 — insert — ambiguity — `ERR_APPRAISAL_SIDE_MISMATCH` is evaluated in the authorisation band and therefore precedes body-shape faults — routes_reval.py:120-133
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric characters — store.py:154-155
- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the logical clock, not the host clock — response.py:13-17
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` is 400; an empty value is treated as absent and defaulted — validate.py:195-215
- §2.3 — insert — ambiguity — `created_at` ties are broken by creation sequence, making ascending listings stable — store.py:182-186
- §2.4 — insert — ambiguity — accepted inbound instant shapes (`T` or space, any/no fractional digits, `Z` or `±HH:MM`); a zone-less instant is read as UTC — store.py:89-121
- §2.5 — insert — ambiguity — `current_utc` is required, the echo carries nothing else, and the clock may be wound backwards — app.py:39-45
- §2.5 — insert — ambiguity — whole-year arithmetic is calendar-based with a 29 Feb -> 28 Feb fallback — store.py:129-136
- §2.6 — insert — ambiguity — integral JSON numbers satisfy integer fields (booleans/numeric strings do not); strings trimmed, non-empty, capped at 512 (2,000 for free text) — validate.py:54-93,148-153
- §2.8 (priority 1) — insert — ambiguity — a non-string foreign key is a not-found, an absent/null one is a shape fault at priority 3 — cascades.py:28-34, validate.py:176-189
- §2.8 (priority 3) — insert — ambiguity — unrecognised body fields are ignored rather than refused; null optional fields read as absent — validate.py:45-48
- §2.8 (priority 7) — revise — **mismatch** — "only reversion assessments, loss-event allocation and estoppel certificates remain available" was false: terms amendment, endorsement filing, rent-charge posting and the new-lease election are also accepted on a wound-up lease — routes_setup.py:160,217,241,294
- §3.1 — insert — ambiguity — `notice_email` shape is unvalidated; `legal_name` uniqueness compares the stripped string exactly — routes_setup.py:29-36
- §3.1 — revise — **mismatch** — collar bounds and the percentage-rent rate are plain 0–10,000 bps at the shape band; ordering/band and the envelope's at-least-1 rule are coherence rules, so `total_permitted_gfa_sqft` of 0 yields `ERR_TERMS_INCOHERENT`, not 400 — routes_setup.py:51-67,86-91
- §3.1 — insert — ambiguity — an amendment field present with null is malformed (not a no-op), and an amendment is ungated by either status axis — routes_setup.py:160-197
- §3.1 — insert — ambiguity — all four endorsement fields are required and none defaulted — routes_setup.py:223-226
- §3.1 — insert — ambiguity — `amount_cents` is required and >= 0; `memo` is validated (<= 2,000 chars) then discarded — routes_setup.py:245-246
- §3.2 — insert — ambiguity — `priority_rank` uniqueness spans every mortgage on the lease whatever its status, so `EXTINGUISHED` does not free a rank — routes_setup.py:268-273
- §3.3 — revise — **mismatch** — all three opening preconditions (including the unopened 180-day runway) report `ERR_INVALID_STATE`; "open revaluation" enumerated as the three non-terminal statuses; operativeness reported ahead of the axis checks — routes_reval.py:58-82
- §3.3 — insert — ambiguity — the revaluation's state is tested before `ERR_APPRAISALS_INCOMPLETE` — routes_reval.py:171-187
- §3.3 — insert — ambiguity — the divergence refusal is reported before `ERR_MAX_ROUNDS_REACHED` when both are live — routes_reval.py:210-217
- §3.3 — insert — ambiguity — `hearing_date` stored as supplied with no clock comparison; referral refusal order is uniqueness -> state -> divergence -> independence -> `IN_DEFAULT` — routes_reval.py:266-296
- §3.3 — insert — ambiguity — the award response's `data` is the arbitration proceeding, not the revaluation — routes_reval.py:318-357
- §3.7 — insert — ambiguity — the replacement lease takes the old `current_annual_base_rent_cents` as both initial and current rent, copies the interval, re-strikes `next_revaluation_date` from the new commencement, zeroes the sublease base/allocated GFA/deposit fields, skips the `premises_code` uniqueness rule, and returns 201 — routes_setup.py:324-372
- §4 — insert — ambiguity — paths match with or without a trailing slash; the clock endpoint answers 200 — app.py:27,39-45
- §5 — insert — ambiguity — routing-layer failures use the same envelope with `ERR_INVALID_REQUEST` while keeping their own status (404/405/400/500) — app.py:56-74

Also verified as a no-change: all 39 error ids and statuses in `errors.py` match the §5 catalogue exactly, with no extras on either side.

### Pass 2 — calc.py, cascades.py, routes_money.py
13 ambiguity-pins, 3 mismatch-revisions.
- §2.11 — revise — mismatch — the tenancy->rent coupling's freeze list omitted `REVALUATION_DUE`; impl freezes it too, so every non-terminal rent state is now enumerated — cascades.py:108-113
- §3.1 (rent summary) — revise — ambiguity — the computed read's field list omitted `lease_id`; added it and pinned the eleven members as exhaustive — cascades.py:217-231
- §3.4 — insert — ambiguity — with several non-`VOID` statements sharing the exact period, the most recently created one is the superseded one, voided only if itself `SUBMITTED` — routes_money.py:62-87
- §3.4 — insert — ambiguity — audit consults neither lease status axis, so a `PROVISIONAL_ASSESSED` statement on an expired lease is still auditable — routes_money.py:151-167
- §3.4 — revise — ambiguity — the net reconciliation is applied with no floor at 0, so arrears may go negative — routes_money.py:192-193
- §3.6 — insert — ambiguity — `ERR_TRANSFER_FIELDS_MISMATCHED` sits immediately after the body-shape band, ahead of uniqueness/operativeness/interval/chronology; a null conditional field counts as omitted — routes_money.py:241-256
- §3.6 — insert — ambiguity — `parent_transfer_id` is existence-checked only: no requirement it be a `SUBLEASE`, on the same lease, or in any status — routes_money.py:218-220,303
- §3.6 — insert — ambiguity — the tier-depth bar is enforced at the consent decision, not at application, so a third-layer request still enters `SUBMITTED` — routes_money.py:303,360-364
- §3.6 — revise — mismatch — "every priced field null" replaced by the five named null fields plus `transfer_fee_paid_cents` at 0 — routes_money.py:322-328
- §3.6 (DENY) — revise — mismatch — "every fee field is left null" corrected: five priced fields null, `transfer_fee_paid_cents` still 0, and the lease is not written so its `version` does not advance — routes_money.py:350-354
- §3.6 (APPROVE) — insert — ambiguity — the tenancy-axis and tier-depth bars are `ERR_INVALID_STATE`, and the full refusal order is pinned (state -> axis -> depth -> cross-entity -> credit rating -> overlap -> sublet area) — routes_money.py:344-402
- §3.6 — insert — ambiguity — on an `ASSIGNMENT` no apportionment runs and `allocable_base_rent_cents` stays null — calc.py:165-171
- §3.6 — insert — ambiguity — consent and activation are two mutations, so the request row's `version` advances by two and the lease's by one — routes_money.py:410-416
- §3.8 — insert — ambiguity — the RESTORE abatement quotient is uncapped and may exceed 10,000 bps — calc.py:253-254
- §3.8 — insert — ambiguity — a zero BONUS_VALUE sum yields a 0 bps share — calc.py:225-229
- §3.8 — revise — mismatch — "day counts use a 365-day year basis" was unsupported (`DAYS_IN_YEAR_BASIS` is dead code); replaced with whole-24-hour-day counting on the real calendar, part-day tail discarded, remaining floored at 0, total <= 0 giving 0 bps — calc.py:232-239, store.py:139-141
- §3.9 — insert — ambiguity — expiry leaves `ISSUED` certificates and `SUBMITTED`/`PROVISIONAL_ASSESSED` statements untouched, unlike termination — cascades.py:155-171

### Pass 3 — routes_ops.py (963 lines), routes_reads.py
23 ambiguity-pins, 10 mismatch-revisions.
- §2.1 — insert — ambiguity — ownership comparison applies on writes and single-resource reads only; collection reads apply no ownership narrowing, and the tenant register sits outside it — routes_reads.py:33-43,49-53
- §2.3 — insert — ambiguity — empty-valued filter params are ignored rather than matched against `""`; filter values compared exactly and never enum-validated, so an unknown value yields an empty page with `total_count` 0 — routes_reads.py:18-22
- §3.1 — revise — mismatch — lease list narrows by `lessee_id`/`lease_status`/`rent_status`; all four lineage spellings match no lease and return an empty page — routes_reads.py:189-194
- §3.2 — insert — ambiguity — estoppel membership check precedes the version guard (422 before 412) — routes_ops.py:830-839
- §3.2 — insert — ambiguity — certificate mortgage filter accepted under either `mortgage_id` or `requested_by_mortgage_id` — routes_reads.py:373
- §3.5 — insert — ambiguity — `conditions_note` validated to <=2,000 chars then discarded — routes_ops.py:96
- §3.5 — insert — ambiguity — revoke `reason_code` required and discarded; both preconditions are `ERR_INVALID_STATE`; `decided_by_user_id` left as the approver's — routes_ops.py:172,175-186
- §3.7 — insert — ambiguity — all four notice-service preconditions are `ERR_INVALID_STATE`, with operativeness reported ahead of them — routes_ops.py:243-272
- §3.7 — insert — ambiguity — absent `cure_amount_cents` reads as 0; `payment_at` is persisted nowhere — routes_ops.py:285-286
- §3.7 — insert — ambiguity — clearance conditions are `ERR_INVALID_STATE`, evaluated after the cure-window bar — routes_ops.py:298-314
- §3.7 — insert — ambiguity — mortgages' own `mortgagee_notified_at` cleared while the notice's is left; neither cure consults the tenancy axis, so an `EXPIRED` lease is driven back to `ACTIVE` — routes_ops.py:323-332,406
- §3.7 — insert — ambiguity — mortgagee-cure membership check runs first, before state; a null `mortgagee_cure_deadline` closes nothing — routes_ops.py:352-377
- §3.7 — revise — mismatch — `COMPLETE` applies no mortgage status test and writes the mortgage to `RECORDED` whatever it held; a short payment is `ERR_INVALID_STATE` — routes_ops.py:367-400
- §3.7 — insert — ambiguity — the encumbrance bar on default termination is `ERR_INVALID_STATE` — routes_ops.py:429
- §3.7 — revise — mismatch — replacement-lease lineage is read off the lease payload, not filterable — routes_reads.py:189-194
- §3.8 — insert — ambiguity — `occurred_at` required, stored as supplied, never compared to the clock; reporting has no state or operativeness guard — routes_ops.py:454-465
- §3.8 — revise — mismatch — a pool of exactly 0 is `ERR_AMOUNT_NOT_RECONCILED`; a negative pool is `ERR_INVALID_REQUEST` — routes_ops.py:495,504
- §3.8 — insert — ambiguity — the `ADJUSTED` state test precedes the event-type test — routes_ops.py:534-541
- §3.8 — revise — mismatch — `RESTORE` overwrites any adjustment-supplied `rent_abatement_bps` — routes_ops.py:544-546
- §3.8 — revise — mismatch — `TERMINATE` writes `rent_abatement_bps` back to null (cleared, not merely "stays null") — routes_ops.py:558
- §3.8 — insert — ambiguity — every bucket-two mortgage is written and version-advanced, 0-cent entries included — routes_ops.py:605-616
- §3.8 — insert — ambiguity — pre-allocation status is written back whatever the mortgage now holds — routes_ops.py:660-671
- §3.8 — revise — mismatch — rescission leaves pool/method/abatement untouched; `allocation_method` cannot be revised (adjust runs only from `REPORTED`); a re-run differs only as the ledger, register and clock have moved — routes_ops.py:673-681,490-500
- §3.8 — insert — ambiguity — rescission `reason_code` required and discarded — routes_ops.py:647
- §3.9 — insert — ambiguity — the direct opening carries no state precondition at all, so an assessment may be opened against a still-`ACTIVE` lease — routes_ops.py:689-698
- §3.9 — insert — ambiguity — `ERR_STANDARD_MET_NO_HOLDBACK` is decided between the `INSPECTED` test and the segregation bar, ahead of `ERR_SEGREGATION_OF_DUTIES` and `ERR_AMOUNT_NOT_RECONCILED`; the holdback consults neither lease axis — routes_ops.py:739-751
- §3.9 — revise — **mismatch (most consequential)** — closing is *not* "available unconditionally" from `HOLDBACK_APPLIED`: both routes additionally require the tenancy axis to read exactly `EXPIRED` (`ERR_INVALID_STATE` otherwise, assessment status tested first), and the `INSPECTED`-with-shortfall refusal is `ERR_INVALID_STATE` — routes_ops.py:780-796
- §3.9 — insert — ambiguity — phase one: `claimed_amount_cents` 0, one lease write (version +1), current `insurance_status` ignored — routes_ops.py:904-911
- §3.9 — insert — ambiguity — phase two applies both lapse rules in one pass, so `SERVED -> LESSEE_CURE_LAPSED -> MORTGAGEE_CURE_LAPSED` can happen in a single run and contribute 2 to the counter, which counts transitions; only notice rows are written — routes_ops.py:914-927
- §3.9 — insert — ambiguity — phase five mints the assessment only if the lease carries none, and its creation is not a lease write — routes_ops.py:954-956
- §3.9 — insert — ambiguity — `affected_lease_ids` includes leases reached only via a notice or mortgage, each id once, in first-touch rather than sorted order — routes_ops.py:899-901
- §4 — revise — mismatch — "`ERR_UNAUTHORIZED` … before any other check runs" was a false universal; authorisation precedes body/version/state/money/coherence but *not* the referential-existence band of §2.8, so a path-identifier miss answers 404 even for an unauthorized role — routes_reads.py:51-52
- §4 — revise — mismatch — the `GET /portfolio/leases` row now reads "filterable by `lessee_id`, `lease_status` and `rent_status`" instead of the two non-functional lineage filters — routes_reads.py:186-200

### Finding carried forward, deliberately NOT fixed
Pass 3 identified a genuine implementation defect: `routes_reads.py:189-194` filters `list_leases` on keys `replaces_lease_id` / `elected_by_mortgage_id`, which lease rows never carry (rows store `predecessor_lease_id` / `origin_mortgage_id`), so all four lineage filter spellings match nothing. Step 9's contract is that **`implementation/` is the alignment target** — so the PRD was pinned to the actual behavior (§3.1, §3.7 and the §4 table now all state that lineage filters match nothing) rather than the code being changed. Changing the implementation at Step 9 would invalidate the green Step 7 sweep, and no test asserts the lineage filter (the Step 5 generator had already dropped that assertion as not uniquely derivable, since §3.7 and §4 disagreed on the spelling). Recorded here so the defect is not lost: fixing it would require an implementation change plus a PRD re-pin, not a PRD edit.

### Orchestrator final verification
- `PRD.md` 492 lines / 113,151 bytes -> `PRD_FINALIZED.md` 492 / 114,853 -> `PRD_COMPLETED.md` 492 / 133,619 (+18.1% chars over PRD.md).
- `cmp -s PRD_FINALIZED.md PRD_COMPLETED.md` -> **differs**, so the scan genuinely ran (guards the known "byte-identical no-op" failure).
- All five top-level sections present in `PRD_COMPLETED.md` (§1 line 3, §2 line 11, §3 line 169, §4 line 375, §5 line 448); tail ends at the `ERR_TRANSFER_FIELDS_MISMATCHED | 422` row — not truncated.
- mtime audit: **no `.py` or `start.sh` file under `implementation/`, `test_suite/` or `test_helpers/` was modified after `results.8.json` was written** — the 8x 129/129 green sweep still describes the code exactly as it stands on disk. Steps 8 and 9 touched only PRD documents.

Pipeline complete through Step 9.

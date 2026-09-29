# Worklog — task_2446_archival_footage_licensing_documentary_clearance

## Step 1: Create task directory — 2026-09-02T19:12:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2446_archival_footage_licensing_documentary_clearance` and its `workspace/` subdirectory. Index 2446 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no index was auto-allocated (32 pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-02T20:33:00.000Z

All three scaffold artifacts for task 2446 are complete and pass the skill's linter.

**Files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2446_archival_footage_licensing_documentary_clearance/`):
- `SCAFFOLD.yaml` (2294 lines) — §1.0–§1.7 only; no `scaffold_difficulty_design` / `scaffold_corner_design` keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1581 lines) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (3411 lines) — single key `scaffold_corner_design`

**Scaffold surface**: 13 entities, 11 state machines, 2 OCC concurrency rules, 9 calculations, 44 validations (priority-ordered 1→44), 47 endpoints, 52 errors, 5 roles (ProductionAdmin, ArchiveResearcher, ClearanceSupervisor, RightsHolderRep as `entity_backed:Archive`, LegalCounsel). Profile: `multi_party_negotiation` / `compliance_audit`, graph topology, cyclic state shape, `segregation_of_duties` role model, immediate consistency, layers = optimistic_concurrency + cascading_side_effects + dual_variant_calculation + ops_run_checkpoint.

**§1.8 (depth)**: 9 rules × 2 = 18 instances, each with a full empty-DB `setup_api_calls` chain. Key mechanics: festival vs all-media fee variant (90563 vs 258750 / 126788 vs 362250, 235462-cent delta), fair-use weighting variant divergence (0.6750 accept vs 0.5700 refuse on identical factors), six-factor fee product rounded once, E&O premium rounded per asset then summed, six-round negotiation cycle, parallel Asset dimensions, 5-hop sweep cascade and 5-hop opinion-letter withdrawal cascade, priority pairs 11▸38 and 20▸26, tier-1 inclusive boundary, 60-vs-61-day renewal window, archive suspension and unbound-E&O cross-entity blocks, half-open term adjacency, 30-day depiction quiet buffer, MFN top-up reversal on termination, E&O rebind without re-rating.

**§1.9 (breadth)**: 78 instances across all nine guide sections — entities 11, state_machines 14, calculations 10, validations 15, endpoints 8, errors 10, rbac 4, complexity_layers 5, consistency_model 1 — of which 54 carry executable recipes and 24 are `excluded_because` stubs pointing at named §1.8 instances. All 52 error ids are reachable or explicitly delegated; both OCC rules, the sweep checkpoint monotonicity, and the immediate-consistency read-after-write are covered.

**Consistency fixes made to SCAFFOLD.yaml while writing the designs** (each closed an unreachable-error or contradictory-precondition hole): posture preconditions on `EOApplication DRAFT→SUBMITTED` and `DeliveryPackage DRAFT→VALIDATED` relaxed to `!= BLOCKED` (with `== OPEN` plus `ERR_EO_NOT_BOUND` moved to `VALIDATED→DELIVERED`); `SubjectRelease SENT→SIGNED` precondition removed; validation 20 scoped to STALE only so `ERR_CHART_SUPERSEDED` (21) is reachable; and validation 10 now carries two explicit exceptions so `ERR_LICENSE_NOT_QUOTED` and `ERR_REVIEWS_INCOMPLETE` are not shadowed by the generic invalid-transition error.

Linter verdict (verbatim):
```
Coverage
  §1.5 endpoints declared:    47
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     54
  Calls scanned (§1.8+§1.9):  869

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
The hard constraint held: no sibling task directory was listed, read, or grepped at any point — every design decision came from the scenario text plus the skill spec and its claim-extraction guide.

## Step 3: Copy shared files — 2026-09-02T20:33:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T20:48:00.000Z

Final verification is clean. The PRD is complete on disk.

**Deliverable:** `workspace/PRD.md`

**Line count:** 471. **Final heading:** `## 5. Error Code Catalogue`. **Last line:** `| \`ERR_COVERAGE_LIMIT_INVALID\` | 422 |` — a real table boundary, no mid-sentence or mid-row truncation. No audit footer or contract-report block was written into the file or any sibling.

**Sections covered**
- §1 Introduction (business context, the "silent drift" problem, flat graph resource model).
- §2 Global Specifications, 12 subsections: 2.1 RBAC (all 5 roles, each `identity` translated, segregation-of-duties model) · 2.2 API Response Structure (fixed block, byte-identical) · 2.3 Pagination & collection filters (limit/offset defaults, min, max, sort order) · 2.4 Common resource properties (`id` UUID no prefix, `created_at`, `updated_at`, `version`) · 2.5 Resource addressing & reference resolution · 2.6 Money/score/rounding discipline · 2.7 OCC · 2.8 Production clearance posture gate · 2.9 Ledger invariants · 2.10 Cascade propagation & chart staleness · 2.11 Logical clock & date arithmetic · 2.12 Validation precedence (all 44 rungs in priority order with error IDs and scopes).
- §3 Business Logic, 8 workflow subsections: production file & asset logging · archive research (rights holders, rate cards, source candidates) · licence opening & rate-card pricing · negotiation rounds, execution, MFN parity · fair-use analysis, opinion letters, withdrawal cascade · subject releases, life rights, negotiated approvals · chart pinning & E&O placement · distributor delivery, rights sweep, renewal.
- §4 Endpoint Definitions — 47 rows, exactly 4 columns (Method, Path, Description, Authorized Role(s)); all 47 scaffold method/path pairs present.
- §5 Error Code Catalogue — 52 rows, exactly 2 columns (Error ID, HTTP Status Code).

**Coverage audit of scaffold §1.1–§1.7**
- §1.1 entities: 13/13 entities, 112/112 unique field names, all 61 fields carrying structured content (enum/default/format/computed/constraints) reconstructible from prose; the `pinned_rows` key-set discrepancy between §1.1 and the endpoint side effect is documented as the union.
- §1.2 state machines: 11/11 machines, 65/65 transitions with `from`/`to` named, each precondition paired with its error ID, each side effect stated. All state values appear as exact strings.
- §1.3 concurrency: 2/2 OCC rules (`expected_production_version`, `expected_license_version`), each with write endpoint, parameter name and 412 error.
- §1.4 calculations: 9/9 in precise prose with inputs, evaluation order, constants, precision and algorithm — posture threshold, rate-card tiered pricing (single terminal round-half-up then floor), MFN retroactive propagation (4 pinned steps, peers by `created_at` ascending, no clawback), E&O premium (round-per-asset-then-sum, with the forbidden sum-then-round order called out), fair-use 4-factor weighted score at 4 decimals with the 0.6000 inclusive threshold, renewal delta floored at zero, and the ledger/coverage computations. No pseudocode, no operator syntax, no fuzzy quantifiers.
- §1.5 validations: 44/44, every `check` matchable to its error ID from §2.12 or §3 narrative.
- §1.6 endpoints: 47/47; all 26 endpoints with side effects (100 individual items) described in workflow narrative.
- §1.7 errors: 52/52 error IDs present in prose and in the §5 table.
- Withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced. All worked examples came from SCAFFOLD.yaml only.

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 112 required, 112 present, 0 missing
- endpoints[].request_body: 78 required, 78 present, 0 missing
- endpoints[].query_params: 19 required, 19 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 44 checked, 44 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 65 checked, 65 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed, 0 missing
- validations[] conditions: 44 checked, 44 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 100 checked, 100 expressed, 0 missing
- entities[].fields[] structured content: 61 checked, 61 reconstructible from prose, 0 missing
- sibling-branch symmetry: 20 groups checked, 20 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 926
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Scaffold inconsistencies handled** (rendered so both readings are satisfiable rather than silently picking one): SubjectRelease `SIGNED` effect on `depiction_status` (endpoint side effect vs. state-machine edge); `APPROVAL_WITHHELD` reachable from either `OBTAINED` or `PENDING`; the License `EXECUTED` precondition mis-citing priority 21 for term overlap (documented under the correct `ERR_LICENSE_TERM_OVERLAP` at priority 38); the E&O review ordering conflict resolved in favor of the explicitly priority-ordered validations table (23 segregation → 24 already-recorded → 25 review-type/role).

**Orchestrator truncation check (independent):** `wc -l` = 470, last heading `## 5. Error Code Catalogue`, 52 `ERR_` table rows, 47 endpoint table rows, file ends on a complete table row. Not truncated — no regeneration needed.

## Step 5: Generate unit tests — 2026-09-02T21:37:00.000Z

Done. The suite is complete and verified.

## Files written

**Stage 1 — `test_helpers/` (9 files)**, at `/home/ubuntu/github/CodingPRD/tasks/task_2446_archival_footage_licensing_documentary_clearance/test_helpers/`: `types.py`, `api_client.py` (47 endpoint methods), `api_errors.py` (52 error ids + HTTP status map registered at import), `constants.py`, `test_users.py`, `factories.py` (18 payload builders), `assertions.py`, `fixtures.py` (~60 setup primitives + 7 composites), `__init__.py` (244 exported names).

**Stage 2 — `test_suite/`**: `conftest.py` plus 15 test files.

## Test counts

**169 tests total — queue A (Difficulty) 61, queue B (Corner) 108.** Verified by AST audit: every test has exactly one trailing `Design:` line, every tag resolves to a real non-stub instance in the right index section, no `skip`/`skipif`/`xfail`/`pytest.skip`, no scaffold or design-index leakage in any docstring or comment. `py_compile` clean; `pytest --collect-only` collects exactly 169 with no import errors and no duplicate function names.

Queue A (all 18 instances, every one at or above the 2-test target): `dual_variant_calc` 6, `combinatorial_formula` 6, `non_linear_state_machine` 8, `transitive_cascade` 12, `priority_pair_validation_conflict` 5, `boundary_precision_check` 6, `cross_entity_state_dependency` 5, `resource_temporal_overlap` 6, `compensating_invariant` 7.

Queue B (all 54 executable instances, every one at or above the 1-test target): `entities` 11, `state_machines` 12, `calculations` 8, `validations` 15, `endpoints` 16, `errors` 23, `rbac` 15, `complexity_layers` 6, `consistency_model` 2.

Per file: test_01 6, test_02 6, test_03 8, test_04 12, test_05 5, test_06 6, test_07 5, test_08 6, test_09 7, test_10 11, test_11 12, test_12 8, test_13 15, test_14 39, test_15 23.

## Instances skipped

**Zero instances were skipped in full.** All 72 executable instances are translated. The 24 `excluded_because:` stubs were correctly not translated (state_machines 3, calculations 5, validations 5, endpoints 3, errors 6, complexity_layers 2).

Individual sub-claims dropped as failing the two-condition filter (the instance itself still has coverage):

- **`rbac/segregation_of_duties_...`** was re-aimed from fair-use acceptance to the E&O review endpoint: §2.12 rung 23 and §3.7 both state segregation of duties "Applies to recording an E&O review", while §3.5 acceptance carries only the letter and score gates. The index's 403-on-acceptance is not PRD-derivable and was not emitted.
- **`state_machines`**: the index's `ERR_INVALID_STATE_TRANSITION` for executing from `TERMINATED` was replaced with `ERR_LICENSE_NOT_QUOTED` per rung 10; posting an `UNDERWRITING` review against a `DECLINED` application was dropped (post-state asserted instead).
- **`endpoints`**: the precedence claim that `ERR_NO_AVAILABLE_SOURCE` outranks an unknown `source_candidate_id` was dropped (rung 6 does not list select-source); whether creating a source candidate bumps `Asset.version` is unspecified, so every test re-reads the version immediately before the action.
- **`entities`**: no assertion on omitted optional `eo_carrier_name` / `festival_premiere_date`; no unknown body keys sent.
- **`calculations`**: `premium_cents is None` on a new application (§3.7), not the index's `== 0`; the index's `renewal_count` / `renewal_delta_cents` assertions dropped as non-fields.

## PRD-wins overrides applied uniformly

`PASSED`→`PASS`/`FAIL` for review outcome; `APPEARANCE`/`DEPICTION`→`SUBJECT_RELEASE`/`LIFE_RIGHTS`/`DEPICTION_AGREEMENT`; `ROUGH_CUT`→`ROUGH_CUT_APPROVAL`; `STOCK_LIBRARY`→`NEWS_ARCHIVE` (no such holder type in the PRD). Two index recipes were also re-sequenced so the intended rule actually fires rather than an earlier precedence rung: the depiction-surcharge test drives `SIGNED → APPROVAL_GRANTED` to reach `OBTAINED` (§3.6 leaves the asset `PENDING` on signing), and the music-leg conditional gives both assets a `SELECTED AVAILABLE` candidate so rung 13 cannot pre-empt rung 36.

## Two fixes I made centrally after the agents reported

- `test_helpers/fixtures.py::record_eo_review` asserted **201** for `POST /eo-applications/{id}/reviews`. §4 reserves 201 for operations that bring a new resource into existence, and a review branch is recorded on the `EOApplication` (no review entity, no review GET) — changed to **200**. This propagates to `record_both_eo_reviews`, `place_bound_eo_cover` and `setup_bound_eo_production`; without it every helper-driven E&O test would have failed spuriously against a conforming implementation.
- Relaxed one over-specified assertion in test_15 (`Production.version == before + 3` across three sweeps → strictly increasing). Version arithmetic is not the instance's asserted outcome and §2.4 does not uniquely fix the number of row mutations per sweep.

Nothing under `workspace/implementation/` was read, written or referenced.

## Step 6: Generate implementation — 2026-09-02T21:37:30.000Z

Implementation complete and verified.

## Files written
All under `workspace/implementation/` (2680 lines of Python total):

- `app.py` — app factory, blueprint registration, error handlers (`ApiError`, 400/404/405/500 all in the envelope), `GET /_health`
- `core.py` — roles, the 53-entry error→HTTP map, `Store` singleton (13 in-memory dicts), logical clock (startup default `2026-08-01T00:00:00Z`), envelope/meta builders, `guard()` auth decorator, body/query validators, date helpers
- `calc.py` — `round_half_up`, rate-card fee pricing, fair-use scaled strength, E&O rating constants, limit constants
- `domain.py` — asset clearance rollup (3 ordered steps), 5-rule posture ladder, production counters/ledger, chart staleness, term/media/territory/depiction overlap tests, rate-card resolution, 404 resolvers
- `routes_production.py`, `routes_archive.py`, `routes_asset.py`, `routes_license.py`, `routes_legal.py`, `routes_release.py`, `routes_insurance.py`
- `requirements.txt`, `start.sh` (executable; pip install is guarded so it's a no-op)

## Endpoints
All 47 scaffold-declared endpoints, machine-diffed against the 47 `method`/`path` pairs in `SCAFFOLD.yaml` — exact match, no gaps, no extras except the non-spec `GET /_health` probe. Includes `POST /_clock/set_current_utc`, the rights sweep, chart pinning with `expected_production_version` OCC, negotiation rounds with `expected_license_version` OCC, MFN settlement on execution, renewal, the E&O fork-join with segregation of duties, and the opinion-letter withdrawal cascade.

## Boot confirmation
Fresh boot from a clean `__pycache__`: `bash start.sh` (PORT=10446) → `GET /_health` HTTP 200, `POST /productions` HTTP 201, `GET /assets` returns `[]` with `total_count: 0`, proving the store is empty on every boot (no seeding, no disk persistence).

## Smoke coverage run against a live server
Three end-to-end passes exercised every module; all behaviours matched the PRD:
- Full happy path: production → archive → rate card → asset → source candidate → select-source → licence (fee `126788`, matching the PRD's worked example) → LICENSOR round → execute → chart pin → E&O submit/reviews/bind → package validate/deliver → LOCKED → DELIVERED → sweeps (post-expiry sweep correctly reported `expired_license_ids`, `lapsed_asset_ids` and dropped `committed_fee_cents` to 0).
- MFN retro-lift on two music legs: executing the second licence at a higher unit rate lifted the first peer's `executed_fee_cents` 100000→200000 with `mfn_topup_cents: 100000`, and stamped `mfn_benchmark_fee_cents: 100000` on the later licence.
- Fair use / releases / insurance: acceptance blocked without an ISSUED letter, then `FAIR_USE`→`CLEARED`; opinion-letter withdrawal cascaded the analysis to `REJECTED` with the AUTO rationale; depiction ±30-day quiet buffer is exact (30 days after → 409, 31 days → 201) and DRAFT releases correctly do not block; premium rating reproduced 93000 cents by hand-check; SOD, duplicate-review, review-role-mismatch, `ERR_REVIEWS_INCOMPLETE`, `ERR_STALE_PRODUCTION_VERSION`, `ERR_STALE_LICENSE_VERSION`, `ERR_OUTSIDE_RENEWAL_WINDOW`, ownership mismatch, pagination bounds and unknown-role 401 all returned the right id and status.

The smoke server has been shut down; no processes left running.

## Step 7: Run tests and iterate — 2026-09-02T22:03:00.000Z

Clean sweep confirmed: all 8 parallel rounds at 169/169, files on disk in `workspace/implementation/results.{1..8}.json`, no `Terminated` in the server logs.

## Summary

**Iterations run:** 2 (sweep → 2 fixes → sweep).

**Round 1 result:** 167/169 in every one of the 8 rounds — the same two tests failed deterministically in all rounds (no flakiness, no load-induced timeouts, no connection resets).

**Tests deleted:** none. Both failures survived STEP 1 (PRD verbatim-covers and uniquely determines the rule).

**Fixes applied to `test_suite/`:**
- `test_suite/test_11_lifecycle_transition_guards.py` — `test_first_failed_review_declines_the_application_and_clears_the_premium` asserted `validate_success(response, 201)` for `POST /eo-applications/{id}/reviews`. PRD §4 states "an operation that brings a new resource into existence answers 201 Created, and every other successful operation — reads, state transitions, action endpoints and the ops utilities — answers 200 OK", and no review resource exists in the PRD (not in §1's resource enumeration, no read endpoint, and §3.7 makes the review a mutation of the `EOApplication`). Corrected to 200 — which is also what every other call site in the suite (`test_helpers/fixtures.py::record_eo_review` and the `validate_success(...)` default) already expects, so this was a lone internal inconsistency in the suite.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes_license.py::create_round` — the rung-10 invalid-state-transition check ran before the rung-33 party/role check, so a `RightsHolderRep` posting a `PRODUCER` round against a `DRAFT` licence got `ERR_INVALID_STATE_TRANSITION` instead of `ERR_PARTY_ROLE_MISMATCH`. PRD §2.12 rung 33 is explicitly scoped "Applies to appending a negotiation round", while rung 10 is scoped to "all eight state-driving operations (production, archive, licence, fair-use analysis, opinion letter, subject release, E&O application, delivery package)" — the negotiation-round endpoint is not one of them, so rung 10 may not pre-empt rung 33. Reordered the two checks; no assertion was weakened and no PRD-required check was removed (the invalid-transition branch still fires for a role-correct out-of-cycle round).

**Fixes applied to `test_helpers/`:** none needed.

**Orchestrator independent verification:** `results.{1..8}.json` all present on disk (timestamps 21:49), each with `passed=169 total=169 failed=0`. Sweep artifacts confirmed — not a claimed-only pass.

## Step 8: Finalize PRD — 2026-09-02T22:06:00.000Z

`workspace/PRD_FINALIZED.md` written: one edit.

**Line counts:** PRD.md 470 → PRD_FINALIZED.md 470 (0.0% line delta; 1 line revised = 0.2% of lines touched).

**Changes**
- §2.12 rung 33 — revise — appended the negotiation-round transition rule: a party that has no move available from the licence's current status (`LICENSOR` needs `DRAFT`/`COUNTERED`, `PRODUCER` needs `QUOTED`) is refused `ERR_INVALID_STATE_TRANSITION`, and that check is evaluated after rung 33 and before rung 34, not at rung 10 — `implementation/routes_license.py:198-218`.

**Per-edit pre-edit search log**

Edit 1 — §2.12 rung 33
- (a) Subject: the error code and precedence position for appending a negotiation round whose declared `party` has no move from the licence's current `status` (the Step 7 impl reorder of rung 10 vs rung 33 in `create_round`).
- (b) Impl paths enumerated: `routes_license.py::create_round` (180-237 — full read: ownership rung 4, body/enum rung 7, stale-version rung 9, party/role rung 33, transition branch 207-213, round-ceiling rung 34 at 216); `routes_license.py::license_state` (280-331 — the licence's own state endpoint, where `ERR_LICENSE_NOT_QUOTED` displaces the generic code for execution and `ERR_INVALID_STATE_TRANSITION` covers lapse/terminate/non-requestable targets); `routes_license.py::renew_license` (335-349); grepped every `ERR_INVALID_STATE_TRANSITION` site across all 11 impl modules (`routes_archive`, `routes_legal` x3, `routes_insurance` x7 — including `record_review:123`, which is *not* one of the eight state endpoints — `routes_release`, `routes_production`, `routes_license` x5); grepped every `negotiation_rounds` / `round_count` / `ERR_PARTY_ROLE_MISMATCH` / `ERR_NEGOTIATION_ROUND_LIMIT` write site to confirm `create_round` is the only round-append path; `calc.py:12` for `NEGOTIATION_ROUND_LIMIT = 6`.
- (c) Wording adjustment: the grep showed `ERR_INVALID_STATE_TRANSITION` also fires outside the eight state-driving operations (notably `routes_insurance.py::record_review:123` for an application not in `SUBMITTED`/`IN_REVIEW`), so I deliberately did **not** touch rung 10's "all eight state-driving operations" scope sentence or turn it into an exhaustive claim; the new text is scoped strictly to the negotiation-round endpoint and describes only where that one check sits. I also kept the phrasing "must have a move available ... any other pairing of party and current status" rather than enumerating forbidden statuses, so it stays true for licences that have left the cycle entirely (`EXECUTED`, `ACTIVE`, `EXPIRING`, `EXPIRED`, `TERMINATED`, `LAPSED`), and left rung numbering untouched to avoid renumbering the ladder.

**No edit made for the other Step 7 item.** The `test_suite/test_11` fix (reviews asserting 201) was a lone test-suite bug: `routes_insurance.py::record_review:175` returns `ok(...)` = 200, and §4's existing sentence already uniquely determines that, with no review resource in §1's enumeration. Prose kept verbatim.

## Step 9: Complete PRD — 2026-09-02T22:20:00.000Z

The patch is complete and verified. Deliverable: `workspace/PRD_COMPLETED.md`

**Size delta**

| | lines | chars |
|---|---|---|
| `workspace/PRD_FINALIZED.md` (source) | 470 | 108,344 |
| `workspace/PRD_COMPLETED.md` | 471 | 117,437 |
| delta | +1 | +9,093 |

65 lines differ (`diff | grep -c '^[<>]'`). The single added line is one new bullet inside §2.2's existing error list; every other change is an in-paragraph insert or revision. No new sections.

**Counts: 23 ambiguity-pins, 12 mismatch-revisions (35 items across 25 edits).**

- §2.2 — insert — ambiguity — unrouted path → `ERR_INVALID_REQUEST` at HTTP 404, unsupported method → same id at HTTP 405 — app.py:33-40
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` is `ERR_INVALID_REQUEST`, not clamped — core.py:275-295
- §2.3 — revise — ambiguity — rate-card list ties inside equal `effective_from_date` break by `created_at` ascending — routes_archive.py:131-136
- §2.7 — revise — mismatch — dropped the claim that a posture recomputation bumps `version`; enumerated the writes that do (lifecycle, asset log, licence create/state/renew, chart pin, sweep) and the conditional ones (analysis decisions, letter-withdrawal cascade, release create/state) — routes_production.py:113-116, routes_legal.py:110-113, routes_release.py:71-76, domain.py:174-184
- §2.7 — revise — ambiguity — non-integer `expected_production_version`/`expected_license_version` is malformed, not stale — routes_production.py:154, routes_license.py:187
- §2.11 — revise — ambiguity — accepted `to_iso8601` forms and `current_utc` rendered to whole seconds with `Z` — routes_production.py:305-319
- §2.12 rung 4 — revise — mismatch — ownership precedes 404 only for a path-borne `archive_id`; licence-addressed ops resolve the licence first — routes_archive.py:74-78, routes_license.py:146-148
- §3.1 — revise — ambiguity — production `to_status` domain, and the reserved-role band check runs after resolution/body validation → `ERR_UNAUTHORIZED` — routes_production.py:69-78
- §3.1 — revise — mismatch — abandonment stamps `reason` or literal `AUTO: production abandoned`, bumps each licence `version`, and runs no asset rollup — routes_production.py:107-111
- §3.1 — revise — mismatch — the rollup writes, bumps and stales charts only when `rights_basis`, `lapse_count` or `licensing_status` actually changes — domain.py:134-144
- §3.2 — revise — ambiguity — archive `to_status` domain; re-requesting the current status → `ERR_INVALID_STATE_TRANSITION` — routes_archive.py:59-62
- §3.2 — insert — ambiguity — optional rate-card quantities must be non-negative numbers, tier bounds non-negative integers — routes_archive.py:84-94
- §3.2 — insert — ambiguity — `quoted_rate_per_30s_cents` and `provenance_confidence` default to 0, not null — routes_asset.py:100-102
- §3.2 — revise — ambiguity — a non-AVAILABLE chosen candidate → `ERR_NO_AVAILABLE_SOURCE`; production untouched; response body is the asset — routes_asset.py:142-156
- §3.3 — revise — ambiguity — `term_months` coherence = whole-month span, or span+1 when a remainder exists — core.py:395-409
- §3.3 — revise — mismatch — licence creation bumps production `version` unconditionally, asset `version` only where the rollup changed it — routes_license.py:137-139
- §3.4 — insert — mismatch — licence-state `to_status` domain; only EXECUTED/LAPSED/TERMINATED requestable; no role narrowing beyond the endpoint list; `termination_reason` null when `reason` omitted — routes_license.py:279-331
- §3.5 — revise — ambiguity — letter attachment has no parent-analysis status precondition — routes_legal.py:120-134
- §3.5 — revise — ambiguity — withdrawal reason arrives as `withdrawal_reason`, null when omitted — routes_legal.py:155,172
- §3.5 — revise — mismatch — hop 4 fires only when posture is BLOCKED, with literal `AUTO: production posture BLOCKED after opinion letter withdrawal` in `created_at` order; hop 5 only if a package was actually suspended — routes_legal.py:191-192, domain.py:200-218
- §3.5 — revise — ambiguity — no cascade hops when the parent analysis is not `ACCEPTED`; response body is the letter — routes_legal.py:176-178
- §3.5 — insert — ambiguity — analysis `to_status` domain; `decision_rationale` optional, written only on decisions, so `REJECTED → DRAFT` retains it — routes_legal.py:83-107
- §3.6 — insert — ambiguity — `depiction_to_date` earlier than the from-date → `ERR_INVALID_REQUEST`; production `version` moves only on a real depiction change — routes_release.py:38-39,71-76
- §3.6 — revise — ambiguity — release-state production bump is conditional, a null `asset_id` touches nothing, plus the `to_status` domain — routes_release.py:103,134-148
- §3.6 — revise — ambiguity — `cut_reference` optional, stored null when omitted — routes_release.py:104,131-132
- §3.7 — revise — ambiguity — `covered_legs` alphabetical, `license_ids` in `created_at` order, pinned letters only from `ACCEPTED` analyses — routes_production.py:120-145, domain.py:69-77
- §3.7 — revise — ambiguity — E&O creation initialises both reviewer-id fields null — routes_insurance.py:85-86
- §3.7 — revise — ambiguity — reviews accepted only from `SUBMITTED`/`IN_REVIEW`, else `ERR_INVALID_STATE_TRANSITION`; `notes` validated but not persisted — routes_insurance.py:119-124
- §3.7 — revise — mismatch — submission open to either endpoint role, not ClearanceSupervisor alone — routes_insurance.py:178-179
- §3.7 — revise — mismatch — binding likewise open to either role; `to_status` domain with only SUBMITTED/BOUND requestable; `policy_number` checked after the rung-44 status test; any non-PINNED chart (SUPERSEDED included) → `ERR_CHART_STALE` — routes_insurance.py:214-231
- §3.8 — revise — mismatch — package validation open to either endpoint role; package `to_status` domain — routes_insurance.py:294-306
- §3.8 — revise — ambiguity — delivery refuses any non-PINNED chart, SUPERSEDED included, with `ERR_CHART_STALE` — routes_insurance.py:349-350
- §3.8 — revise — mismatch — `lapsed_asset_ids` lists swept assets that left `CLEARED` (so `PARTIALLY_CLEARED` counts); production `version` advances on every sweep call — routes_production.py:256-264,290
- §3.8 — insert — ambiguity — non-integer `additional_term_months` → `ERR_INVALID_REQUEST`, pre-empting every other renewal check — routes_license.py:341-343
- §3.8 — revise — mismatch — renewal re-prices against the licence's stamped `rate_card_id` (never re-stamped) and the delta is computed only; no `renewal_delta_cents` field exists anywhere — routes_license.py:379-391

Two impl behaviours were deliberately left unpinned to honour the minimal-patch rule, since neither is observable through the API: §2.9's "maintained incrementally" wording versus `recompute_committed`'s full re-derivation, and the float representation of `strength_score` behind the scaled integer.

**Orchestrator verification:** `workspace/PRD_COMPLETED.md` present (471 lines, 117,437 bytes), ends on a complete error-table row. Pipeline complete.

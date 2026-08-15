# Worklog — task_1774_tissue_bank_allograft_management

## Step 1: Create Task Directory — 2026-08-14T15:06:00.000Z

Task directory `tasks/task_1774_tissue_bank_allograft_management/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Verified both exist; no other task_* directory was touched.

## Step 2: Generate Scaffold — 2026-08-14T16:20:00.000Z

Scaffold generation complete for task_1774_tissue_bank_allograft_management. All three artifacts written and lint-clean.

## Output files
- `/home/ubuntu/github/CodingPRD/tasks/task_1774_tissue_bank_allograft_management/SCAFFOLD.yaml` — §1.0–§1.7 (scenario verbatim, no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1774_tissue_bank_allograft_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`, 18 instances (9 rules × 2)
- `/home/ubuntu/github/CodingPRD/tasks/task_1774_tissue_bank_allograft_management/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`, 80 instances (76 active + 4 excluded_because stubs) across all 9 taxonomy sections

## Design summary
- **Profile**: compliance_audit primary + quota_allocation secondary; layers: cascading side effects, OCC, derived-field reconciliation, rate/threshold triggers; flat topology, cyclic state shape, segregation-of-duties role model (3 SoD pairs: doc-verify vs supplier-approve, excursion report vs resolve, adverse report vs resolve), immediate consistency. 13 entities, 69 endpoints, 56 errors, 7 calculations, 12 state machines, 5 roles, 3 OCC concurrency rules (freezer config, policy supersede-create, policy update), logical clock `/_clock/set_current_utc` with mandated default 2026-08-01T00:00:00Z.
- **Difficulty depth (§1.8)**: dual-variant FIFO vs weighted-average valuation (20003.00 vs 20002.66, verified by execution) and provisional-vs-final supplier score (75 vs 100); combinatorial formulas in two modes (excursion severity with nested min-caps + tier branch → 68/HIGH gating DESTROY; per-lot-line rounding order pinned to 20002.66 vs the forbidden 20002.67); cyclic machines on TissueUnit (quarantine-release) and AdverseReactionCase (reopen); a depth-4 excursion cascade (reading → excursion/freezer → unit quarantine → reservation release → par deficit) and a depth-3 adverse-confirmation cascade to supplier auto-suspension (score 55 < 60); priority conflicts (state-vs-safety, safety-vs-fiscal); boundary precision (temperature exactly at max in-range; par equality no-reorder); cross-entity gates (TissueUnit×Freezer, Shipment×Supplier); two interval semantics (half-open OR-room adjacency-allowed vs closed document-validity touching-conflict); two compensating invariants (physical unit count and monetary valuation conserved across excursion open+release).
- **Corner breadth (§1.9)**: creation/defaults, immutable event entity, system-field smuggling, not-found family with left-to-right nesting, invalid-transition and terminal lockdown per machine, all three OCC stale-version paths, retention boundary at finalized_at + 3650 days (verified 2036-08-07T11:00:00Z), capacity reserve engaging exactly at 80% utilization, expiry/document/hold-until equality boundaries, supplier suspension threshold boundary (60 stays, 55 suspends), pagination envelope, filter+sort (serial ASC on shuffled manifest), FK reverse-reachability, envelope shape, RBAC denials, read-your-writes consistency.

Every numeric assertion was pre-computed with Python; every setup chain was replayed call-by-call against §1.2/§1.4/§1.6 (two replay bugs found and fixed during authoring: a pre-trigger par-level claim that ignored the reservation's effect on the AVAILABLE inclusion set, and a duplicate-serial test whose supplier would have failed an earlier-priority safety gate).

## Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(Coverage line: 69 endpoints, 13 entities, 18 §1.8 instances, 76 §1.9 instances, 1057 calls scanned.)

Initial lint run surfaced 10 violations (valuation GET query params moved into `payload:`; two missing FK reverse GETs fixed by adding `implanted_case_id?` to the units filtered list and a `GET /tissue-bank/freezers` list with `current_excursion_id?`); all fixed and re-run clean. Also corrected two §1.4-vs-§1.6 http-status mismatches (ERR_INVALID_WINDOW / ERR_INVALID_TEMP_RANGE moved to the 400 request-shape row) and added a `document_ref ASC` tie-break to the documents list for deterministic index captures.

## Step 3: Copy Shared Files — 2026-08-14T16:22:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1774_tissue_bank_allograft_management/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T16:40:00.000Z

PRD generated and all three hard contracts pass. 

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1774_tissue_bank_allograft_management/workspace/PRD.md`

**What was produced:** A prose PRD for the Tissue Bank & Allograft Management API — §1 introduction (2 paragraphs, domain-first framing), §2 with 11 subsections (RBAC with all five roles' opaque-identity prose, verbatim §2.2 response envelope, pagination, logical clock + pinned sweep order, common resource properties incl. the `TemperatureReading` no-`updated_at`/`version` exception, nested-resource left-to-right 404 vocabulary, the three OCC rules, the full 11-rung validation priority ladder, precision/rounding, segregation of duties, disposition retention), §3 with 9 lifecycle-grouped subsections (suppliers/documents, shipments, freezers/excursions, unit lifecycle, implant cases/reservations, recalls, adverse reactions, qualification scoring/auto-suspension, par-level/valuation), §4 with a 69-endpoint 4-column table, §5 with a 56-error 2-column table. The withheld difficulty/corner design files were never opened.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 109 required, 109 present, 0 missing
- endpoints[].request_body/input: 46 required, 46 present, 0 missing
- endpoints[].query_params/path_params + system outputs: 16 required, 16 present, 0 missing
  (total deduplicated set: 108 required, 108 present, 0 missing after repair pass)
Status: PASS
```

```
Rule coverage check:
- validations[] priority ladder: 11 rungs checked, 11 expressed in pinned prose order (§2.8), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_*_version + ERR_STALE_VERSION/412 named; missing expected_current_policy_version treated as 0 stated), 0 missing
- state_machines[].transitions: 41 checked across 12 machines, 41 fully expressed (from/to, preconditions+error_id, side effects), 0 missing
- calculations[]: 7 checked (inventory_valuation FIFO+WEIGHTED_AVERAGE with pinned per-lot rounding order and forbidden alternate, qualification scores with 20/15/10/5 penalties and <60 gate, severity score with 40/30/20 caps and 8/6/2 + 0/5/10 tier points, capacity gating with pinned 5-step order and 80.0/2 constants, par deficit with strict comparator, both sweeps with strict-inequality and ordering), 7 fully expressed, 0 missing
- validations[] conditions: 56 error ids, all matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: 69 endpoints checked, cascades and gate scopes expressed, 0 missing
- entities[].fields[] structured content: defaults/initial values/computed semantics reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (RELEASE/DESTROY, CONFIRMED/UNCONFIRMED, direct/reservation issue, 4 recall-sweep status branches, REPORTED/REOPENED investigate, both closed-state reopens), all symmetric, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 609
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verifications: §2.2 matches `section-2.2-response-structure.md` byte-for-byte (confirmed programmatically); all 56 error ids, all state values, and all enum values appear as exact strings; PRD.md ends at §5 with no audit footer. Two coverage gaps found on the first pass (`implant_case_id`, `RESOLVED_RELEASE`/`RESOLVED_DESTROY`) were repaired and re-verified.

## Step 5: Generate Unit Tests — 2026-08-14T17:25:00.000Z

Generation complete for task_1774_tissue_bank_allograft_management.

## What was produced

**`test_helpers/` (Stage 1, 9 files)** — under `/home/ubuntu/github/CodingPRD/tasks/task_1774_tissue_bank_allograft_management/test_helpers/`:
- `types.py` — 13 entity TypedDicts + status/enum vocabulary; `TemperatureReading` correctly carries only `id` + `created_at` (no `version`/`updated_at`) per its append-only nature
- `api_client.py` — `ApiClient(GenericApiClient)` with 73 methods, one per PRD §4 endpoint, including `POST /_clock/set_current_utc`
- `api_errors.py` — all 57 error IDs with HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` plus `assert_supplier_scores`; `assert_temperature_reading` asserts `version`/`updated_at` absence
- `factories.py`, `constants.py` (score penalties, severity caps, 80% reserve trigger, 3650-day retention), `test_users.py` (all roles opaque identity → shared constants, plus second-user variants for SoD/ownership tests)
- `fixtures.py` — tiered composites: `setup_qualified_supplier` (dual-doc verify + cross-user approve), accepted/available unit chains, reserved→issued→implanted lifecycle bundles, excursion openers, par-policy creation, and `setup_valuation_population()` (the two-shipment, one-implanted BONE population shared by the valuation difficulty instances)

**`test_suite/` (Stage 2)** — `conftest.py` + 9 concern-grouped files, **112 tests total**, every one tagged with exactly one terminal `Design:` line.

## Verification results (all green)

- **Coverage**: all 18 difficulty instances × ≥2 tests (36 tests); all 76 non-stub corner instances × ≥1 test (76 tests). The 4 `excluded_because:` stubs were not translated; their `difficulty_instance` cross-references all resolve.
- **Tags**: every docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line; all 112 resolve to real instances in the source YAMLs.
- **Citations**: 179 quoted citation spans extracted from docstrings — all verbatim-match `workspace/PRD.md` (whitespace-normalized), including the §2.8 ladder rung lines with their `**bold**` markers.
- **No gaps papered over**: zero `skip`/`skipif`/`xfail` markers; no test invented outside the two indices. Every instance passed the PRD-first filter — this PRD covers all asserted rules (the empty-population valuation case is derivable: zero on-hand lots → sum of zero lot lines = 0).
- **Syntax/imports**: `py_compile` clean, `pyflakes` clean (only expected barrel-export re-export notes), and `pytest --collect-only` collects all 112 tests with no import errors.

One notable design decision: retention boundary math — `finalized_at` 2026-08-10T11:00:00Z + 3650 days lands on 2036-08-07 (3 leap days in the interval), matching the corner instance's pre-computed dates; the test asserts rejection one day before and a 204 purge exactly at the boundary.

## Step 6: Generate Implementation — 2026-08-14T17:25:00.000Z

Complete. The implementation is at `/home/ubuntu/github/CodingPRD/tasks/task_1774_tissue_bank_allograft_management/workspace/implementation/`.

## What was built

Python + Flask in-memory REST API implementing all 47 endpoints from the scaffold's endpoint table (suppliers/documents, shipments, tissue units, freezers/readings/excursions, implant cases, reservations, recalls, adverse reactions, par-level policies, valuation, disposition records, and `/_clock/set_current_utc`).

**Layout**: `app.py` (entry, error handlers), `db.py` (empty-at-boot dict store + monotonic seq), `errors.py` (full error catalog with exact IDs/statuses), `response.py` (`meta`/`response_type`/`data` envelope, pagination fields `limit`/`offset`/`total_count`/`has_more`), `middleware.py` (X-User-ID/X-User-Role auth, five roles), `validate.py` (request-shape validators), `services/domain.py` (derived fields, cascades, sweeps, serializers), `routes/*.py` (12 blueprints), `start.sh` (guarded pip install + `exec python3 app.py`, `0.0.0.0:$PORT`).

**Fidelity decisions traced to PRD/scaffold** (cross-checked against SCAFFOLD_CORNER_DESIGN.yaml and SCAFFOLD_DIFFICULTY_DESIGN.yaml):
- Validation ladder enforced exactly: auth(400) → role(403) → path existence(404) → body shape(400) → OCC(412) → state(409) → compliance(403) → temporal(409) → structural(409) → referential(422) → fiscal(402). Verified the pinned conflict cases (shape-before-state on shipment reject, state-beats-safety on issue of EXPIRED unit, safety-beats-fiscal on accept of suspended supplier over cap).
- Logical clock starts at `2026-08-01T00:00:00Z`, second-precision comparisons, strict `>` sweeps in pinned order (documents → units → reservations); `created_at`/`updated_at` render with 3 fractional digits, all business datetimes as `...Z` seconds.
- Scores, capacity bookkeeping (80% reserve, pinned evaluation order), excursion severity (ceil deviation, whole-hour truncation, caps), par signals (strict `<`), and valuations (exact `Fraction` weighted-average with per-lot-line round-half-up, FIFO by received_at/created_at) are computed from live state, so all cascades reconcile automatically. Supplier auto-suspension gate fires on every score-mutating event.
- SoD pairs (approve-vs-verifier, manual-excursion resolve-vs-reporter, adverse resolve-vs-reporter), OCC on freezer PUT / policy create+PUT, half-open OR-room vs closed document-window overlap semantics, 3650-day retention boundary, zero-match recall auto-close, TemperatureReading without `version`/`updated_at`.
- No seeding at startup; store starts empty on every boot.

## Verification

- `bash start.sh` contract: fresh-process boots in ~680 ms (pip guard makes repeat boots a no-op), empty store after reboot, correct clock default.
- 184-check smoke suite + 30-check edge suite (both passed, 0 failures) covering every design-file scenario: capacity reserve at exactly 80%, severity 25/82 class boundaries, WA 20002.66 vs FIFO 20003 divergence, score 65→55 auto-suspension chains, recall sweeps (7-unit match incl. RESERVED release and IMPLANTED counting), sweep equality boundaries, OCC 412 replays, SoD rejections, retention-boundary 204, pagination envelope, and the full 404 vocabulary.

One judgment call worth noting: PRD §2.8's ladder (state rung before temporal rung) was applied over the scaffold's per-transition precondition listing order where they conflicted (e.g., record-implantation checks unit ISSUED before the implant window), per the skill's PRD-wins rule.

## Step 7: 8-Round Parallel Stability Sweep — 2026-08-14T17:45:00.000Z

Ran `prd-bench-local-run --isolation per-test-server --timeout 120 --test-timeout 30` in 8 concurrent background rounds against `workspace/implementation/`.

**Result: all 8 rounds clean — 112/112 passed, 0 failed, 0 errors, 0 skipped in every round** (verified per-test `status` field, not just summary counters). No flaky tests surfaced; no fixes, no deletions required this pass.

## Step 7 (orchestrator verification) — 2026-08-14T17:50:00.000Z

Independently verified all 8 `results.${i}.json` files: every round reports `passed: 112, total: 112`. Subagent summary verbatim:

**Summary**

- **Iterations run:** 1 (single 8-round parallel stability sweep; exit condition met on the first sweep).
- **Result:** All 8 rounds passed — 112/112 tests, 0 failed, 0 errors, 0 skipped in every round (verified via per-test `status` fields in each `results.${i}.json`, not just summary counters).
- **Tests deleted:** None.
- **Fixes applied to `test_helpers/`:** None.
- **Fixes applied to `implementation/`:** None.

## Step 8: Finalize PRD — SKIPPED — 2026-08-14T17:50:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` is produced. Step 9 will start from `PRD.md`.

## Step 9: Complete PRD — 2026-08-14T17:48:00.000Z

The diff confirms all 26 edits landed cleanly. Work is complete — here is the summary.

## Summary

**Source:** `workspace/PRD.md` (Step 8 was skipped; no PRD_FINALIZED.md existed) → `workspace/PRD_COMPLETED.md`
**Size:** 379 lines / 62,873 bytes → 380 lines / 67,291 bytes (+1 line, +4,418 bytes / +4,397 chars)
**Counts:** 26 changes total — **21 ambiguity-pins**, **5 mismatch-revisions**. No new sections added; all changes are inline paragraph inserts/revisions.

### Changes

- **§2.1** — insert — ambiguity — header values are whitespace-stripped and empty/whitespace-only values count as missing — `implementation/middleware.py:28-30`
- **§2.2 (success envelope)** — revise — mismatch — 204 purge is an exception to the envelope: empty body, not `data: {}` — `implementation/routes/dispositions.py:62`
- **§2.2 (error envelope)** — insert — ambiguity — undeclared paths / unsupported methods answered with `ERR_NOT_FOUND` (404) in the standard error format — `implementation/app.py:28-34`
- **§2.3** — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`; `has_more` = `offset + page_len < total_count`; filters are exact-equality, pre-pagination, and yield empty pages on no match — `implementation/validate.py:117-136`, `implementation/response.py:28`
- **§2.4** — insert — ambiguity — (a) backward `to_iso8601` rejected `ERR_INVALID_REQUEST`, equal instant accepted and re-runs sweeps — `implementation/routes/clock.py:25-27`; (b) `reservations_expired` includes unit-sweep-driven expirations, `suppliers_auto_suspended` counts once per supplier — `implementation/services/domain.py:411-493`; (c) reservation sweep processes `hold_until` ASC, ties `created_at` ASC — `implementation/services/domain.py:478-482`; (d) client datetimes parsed as ISO 8601 Z/offset, normalized to UTC, truncated to seconds; logical-clock instants rendered at second precision — `implementation/util.py:37-54`
- **§2.5** — revise — ambiguity — `version` starts at **1** on creation — `implementation/services/domain.py:49`
- **§2.6** — insert — ambiguity — ladder placement of body-reference existence: directly after request shape, except under a parent with ownership/state preconditions (implant-case endpoints) where those run first; always before the referenced entity's own state/compliance checks — `implementation/routes/shipments.py:87-92`, `implementation/routes/units.py:112-115`, `implementation/routes/cases.py:140-147,181-186,226-237`
- **§2.8 rung 4** — insert — ambiguity — malformed/non-object JSON → `ERR_INVALID_REQUEST`; absent body treated as `{}`; unrecognized body fields (incl. smuggled system keys) ignored — `implementation/validate.py:15-25`, `implementation/routes/shipments.py:65`
- **§2.9** — revise — ambiguity — `utilization_pct` rendered round-half-up 2dp; the 80% reserve trigger uses the exact unrounded ratio — `implementation/services/domain.py:142-147`
- **§2.10** — revise — ambiguity — "most recently verified required-type document" ranks across all ever-verified required-type docs, including since-expired ones — `implementation/routes/suppliers.py:105-112`
- **§3.1** — revise — ambiguity — `DISQUALIFIED` blocks supplier-state mutations and new document submissions, but verify/reject of already-submitted documents remains lawful — `implementation/routes/suppliers.py:207-208` vs `240-263`
- **§3.2 (minting)** — insert — ambiguity — each minted unit also carries `received_at` copied from the shipment's receipt instant — `implementation/routes/shipments.py:133`
- **§3.2 (rejection)** — revise — ambiguity — rejection moves **every** minted unit to `RETURNED_TO_SUPPLIER` regardless of current status (clock-swept `EXPIRED` included), with per-unit dispositions; occupancy drops only for units still stored — `implementation/routes/shipments.py:207-215`
- **§3.3 (readings)** — revise — mismatch — PRD said "the bounds snapshot lives on the reading"; impl carries no bounds fields — the `in_range` verdict is computed once at record time and frozen — `implementation/routes/freezers.py:139-155`, `implementation/services/domain.py:605-616`
- **§3.3 (excursion bookkeeping)** — insert — ambiguity — `last_reading_at` initialized to the opening instant, advancing per linked reading — `implementation/services/domain.py:321`, `implementation/routes/freezers.py:170`
- **§3.4** — insert — ambiguity — unit roster serial-ascending ties broken by creation order — `implementation/routes/units.py:54`
- **§3.5 (reservations)** — insert — ambiguity — reserving against a non-`SCHEDULED` case fails `ERR_CASE_INVALID_STATE` — `implementation/routes/cases.py:182-183`
- **§3.5 (record-implantation)** — insert — ambiguity — the response returns the implanted unit object — `implementation/routes/cases.py:168`
- **§3.6 (draft)** — insert — ambiguity — a recall may be drafted against a supplier in any status — `implementation/routes/recalls.py:42-44`
- **§3.6 (zero-match)** — insert — ambiguity — `activated_at` remains stamped when the recall auto-closes `NO_MATCH` — `implementation/routes/recalls.py:76-77,108-111`
- **§3.7** — insert — ambiguity — adverse-reaction reporting is not gated on the case's `status` — `implementation/routes/cases.py:224-255`
- **§3.8** — revise — mismatch — score-mutating event list now includes adverse-reaction **report** (impl evaluates the auto-suspension gate on report) — `implementation/routes/cases.py:252-254`
- **§3.9 (update)** — insert — ambiguity — updating a non-`ACTIVE` policy → `ERR_INVALID_REQUEST` once OCC passes — `implementation/routes/policies.py:88-89`
- **§3.9 (valuation)** — insert — ambiguity — `tissue_type`/`method` arrive as query parameters with a JSON-body fallback; empty population → `on_hand_count` 0, `total_value` 0 — `implementation/routes/policies.py:101-111`, `implementation/services/domain.py:261-262`
- **§3.9 (fiscal cap)** — revise — mismatch — PRD's "This is the method the fiscal cap projects" sat in the FIFO paragraph; impl projects the **weighted-average** valuation at acceptance — `implementation/routes/shipments.py:170-188`, `implementation/services/domain.py:272-279`
- **§4** — revise — mismatch — purge returns "empty response body (no envelope)", not "an empty data object" — `implementation/routes/dispositions.py:62`

### Verification notes

Everything else in the implementation was found already uniquely pinned by the PRD, including: the full priority-ladder ordering (shape-before-state on reject/resolve endpoints, OCC before business rules, compliance before structural, referential last), severity scoring formula and class boundaries, capacity derivation order and admission equality, excursion open/resolve cascades with hold-attribution rules, recall sweep per-status handling and `affected_unit_count` semantics, implant window bounds, retention equality at exactly `finalized_at + 3650d`, OCC defaults for policy creation, WA per-lot round-then-sum ordering, and FIFO consumption ordering.

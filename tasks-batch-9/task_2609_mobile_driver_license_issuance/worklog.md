# Worklog — task_2609_mobile_driver_license_issuance

## Step 1: Create task directory — 2026-09-03T19:10:15.353Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2609_mobile_driver_license_issuance` and `.../workspace` (pre-assigned path from the invocation; no index scan performed, per orchestration instructions).

## Step 2: Generate scaffold — 2026-09-03T21:02:48.177Z

All three scaffold artifacts for task 2609 (Mobile Driver License Issuance) are complete and lint-clean.

## Files

| File | Lines |
|---|---|
| `.../SCAFFOLD.yaml` | 2336 |
| `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1774 |
| `.../SCAFFOLD_CORNER_DESIGN.yaml` | 5062 |

Each ends at a real structural boundary (final `shared_operations` entry / final `assert:` line). `SCAFFOLD.yaml` contains no `scaffold_difficulty_design` or `scaffold_corner_design` key; each design file has exactly one top-level key.

## SCAFFOLD.yaml counts
`api_prefix: /mdl`, `difficulty_level: expert_plus` — 14 entities, 55 endpoints, 43 errors, 7 calculations, 8 state machines (+2 §1.2.1 concurrency rules), 32 validation rows (single ascending priority ladder), 6 roles (`role_model: segregation_of_duties`). Complexity layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; entity_topology graph; state_machine_shape parallel; consistency_model immediate.

## SCAFFOLD_DIFFICULTY_DESIGN.yaml — 18 instances, 2 per rule
dual_variant_calc 2, combinatorial_formula 2, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

## SCAFFOLD_CORNER_DESIGN.yaml — 93 instances across all nine sections
entities 12, state_machines 14, calculations 15, validations 11, endpoints 6, errors 19, rbac 6, cross_cutting_complexity_layers 8, consistency_model 2 — 65 with full `test_recipe`s, 28 `excluded_because:` stubs (each citing an existing §1.8 instance by `rule_id / name`, none carrying a recipe). All 43 error codes in the §1.6 catalog are triggerable: 33 by a §1.9 recipe, the rest by a §1.8 instance cited from a stub. Every instance name is unique across both design files; the only non-ASCII characters are intentional `§` symbols in comments.

## Lint verdict (verbatim, final run)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2609_mobile_driver_license_issuance/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2609_mobile_driver_license_issuance/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2609_mobile_driver_license_issuance/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    55
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     65
  Calls scanned (§1.8+§1.9):  1109

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Notes worth relaying: no sibling task directory was read at any point; two corrections were applied in this final pass — a stub grounds reference to a non-existent calculation name (`identity_proofing_assurance_score` → `proofing_assurance_score`) and a duplicate instance name (`proofing_variant_divergence_corner` → `proofing_assurance_variant_divergence_layer_corner`), plus normalization of the seven newest stub refs to the spec's `rule_id / instance_name` form.

## Step 3: Copy shared files — 2026-09-03T21:02:48.177Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T21:14:51.993Z

PRD generated and verified.

**Output:** `.../workspace/PRD.md` — **500 lines**, 106,893 bytes. Written incrementally (1 Write + 6 heredoc appends + 2 targeted edits); no truncation.

**Section list**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 2.1 Operators, Roles and Identity Binding · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Common Resource Properties and the Logical Clock · 2.5 Left-to-Right Resolution of Nested Resources · 2.6 The Rejection Ladder · 2.7 Optimistic Concurrency on Parent Records · 2.8 Two Independent State Axes on a Digital Credential · 2.9 Cascade Discipline, Compensating Actions and Conserved Counters · 2.10 Fees, Scores, Precision and Rounding · 2.11 Privacy Invariants · 2.12 Three Flavours of Interval Semantics
- §3 Business Logic & Workflows (9 domain-derived subsections) — 3.1 Governing the Jurisdiction: the Interoperability Profile and the Trust List · 3.2 Enrolment and Identity Proofing · 3.3 Binding the Handset · 3.4 Provisioning and Activating a Digital Credential · 3.5 Propagating Change to the Handset · 3.6 Loss, Suspension, Revocation and the Near-Real-Time Ledger · 3.7 Admitting Verifiers and Reader Applications · 3.8 Presentation, Consent and Data Minimisation · 3.9 Privacy Oversight: the Exposure Index, Invoicing and Compensation
- §4 Endpoint Definitions — 55 rows, 4 columns
- §5 Error Code Catalogue — 43 rows, 2 columns

**Tail confirmed complete:** file ends on the final §5 table row (`| ERR_VERIFIER_ACCOUNT_DELINQUENT | 402 |`) — a real section boundary, no audit footer, no mid-sentence cut.

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 161 required, 161 present, 0 missing
- endpoints[].request_body: 71 required, 71 present, 0 missing
- endpoints[].query_params: 19 required, 19 present, 0 missing
- computed-read output keys: 22 required, 22 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 32 checked, 32 expressed in prose (full ordered ladder in §2.6, every applies_to scope enumerated: 4 endpoints for physical-credential eligibility, 8 for ownership, 2 each for OCC / assurance-sufficiency / protection-method / retention-ceiling / verifier-trust, 3 for device-binding), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (POST /mdl/credentials + expected_device_version + ERR_STALE_DEVICE_VERSION 412; POST /mdl/trust-list-snapshots + expected_interop_profile_version + ERR_STALE_INTEROP_VERSION 412), 0 missing
- state_machines[].transitions: 47 checked across 7 machines, 47 fully expressed (both DigitalCredential axes, the single cross-axis coupling, all 3 cyclic loops, compound UpdateOrder rollup), 0 missing
- calculations[]: 7 checked, 7 fully expressed incl. all 4 dual-variant pairs, every constant embedded in business context, pinned rounding/evaluation orders stated, 0 missing
- validations[] conditions: 32 checked, 32 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 55 checked, 55 expressed (5-hop propagation cascade, 3-hop loss cascade + 3-hop compensation, trust-list pointer staleness fan-out), 0 missing
- entities[].fields[] structured content: 161 checked, 161 reconstructible from prose (every enum set, default, initial value, counter definition), 0 missing
- sibling-branch symmetry: 7 groups checked (attest PASS/FAIL, adjudicate VERIFY/RETURN/DENY, consent APPROVE/DENY, presentation fork CONSENT_PENDING/BLOCKED_BY_POLICY, delivery first/second failure, physical-credential SUSPENDED/VALID/REVOKED, trust-decision 5 branches), 7 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1025
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verifications: §2.2 is byte-identical to `section-2.2-response-structure.md`; no operator syntax (`>=`, `+=`, `==`, `min()`, `round_half_up`, `≥`) leaks outside code fences anywhere in §1–§3; no fuzzy quantifiers; §3 contains zero markdown tables and zero field lists. Note the scaffold's own header comment says "44 endpoints / 42 error codes" but the actual `endpoints[]`/`errors[]` arrays hold **55** and **43** — the tables were generated from the arrays, not the comment.

Per the hard constraint, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

**Orchestrator truncation check (independent):** `wc -l` = 500; `tail -20` ends on the final error-catalogue row; heading scan shows all of §1–§5 present with §4 at line 390 and §5 at line 452. Not truncated — no regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T22:14:46.379Z

All 18 test files are complete and verified. Final state:

## Files written

**`.../test_helpers/`** (Stage 1)
| file | lines |
|---|---|
| `constants.py` | 210 |
| `test_users.py` | 88 |
| `api_errors.py` | 145 |
| `types.py` | 308 |
| `api_client.py` | 417 |
| `factories.py` | 231 |
| `assertions.py` | 129 |
| `fixtures.py` | 489 |
| `__init__.py` | 47 |

**`.../test_suite/`** (Stage 2)
| file | lines | tests |
|---|---|---|
| `conftest.py` | 23 | — |
| `test_01_dual_variant_calculations.py` | 253 | 4 |
| `test_02_combinatorial_fee_formulas.py` | 241 | 4 |
| `test_03_non_linear_state_machines.py` | 231 | 4 |
| `test_04_transitive_cascades.py` | 225 | 4 |
| `test_05_rejection_ladder_priority.py` | 219 | 4 |
| `test_06_boundary_precision.py` | 147 | 4 |
| `test_07_cross_entity_state_dependency.py` | 220 | 4 |
| `test_08_resource_temporal_overlap.py` | 230 | 4 |
| `test_09_compensating_invariants.py` | 202 | 4 |
| `test_10_entity_records.py` | 425 | 12 |
| `test_11_state_transitions.py` | 495 | 9 |
| `test_12_calculation_corners.py` | 442 | 7 |
| `test_13_validation_rules.py` | 514 | 9 |
| `test_14_endpoint_behaviour.py` | 292 | 4 |
| `test_15_error_catalogue.py` | 583 | 12 |
| `test_16_role_permissions.py` | 380 | 6 |
| `test_17_concurrency_and_layers.py` | 310 | 4 |
| `test_18_consistency_model.py` | 151 | 2 |

## Totals
- **101 test functions / 103 collected cases** (one `parametrize` of 3 in `test_06`), each carrying exactly one trailing `Design:` line — verified programmatically against both design yamls: **zero invalid tags, zero dual tags, zero tags pointing at stubs**.
- `pytest --collect-only` succeeds; every file passes `ast.parse` and `pyflakes` (the only pyflakes output is the three deliberately `noqa`-marked lines in `conftest.py`).
- No `skip`/`xfail`/mocking anywhere; no occurrence of the word "scaffold" in any generated file; both directories sit at the task root, nothing under `workspace/`.

## Coverage
- **Queue A (§1.8 difficulty):** 18/18 instances translated, **exactly 2 tests each** = 36 tests. **Zero skipped.**
- **Queue B (§1.9 corner):** 65/65 non-stub instances translated, 1 test each = 65 tests. **Zero skipped.** The 28 `excluded_because:` stubs were deliberately not translated, per the design-index contract: entities 12/12, state_machines 9/9 (5 stubs), calculations 7/7 (8 stubs), validations 9/9 (2 stubs), endpoints 4/4 (2 stubs), errors 12/12 (7 stubs), rbac 6/6, cross_cutting_complexity_layers 4/4 (4 stubs), consistency_model 2/2.

## Two deliberate deviations from design assert-text (PRD-uniqueness driven)
1. **`rbac/same_user_cannot_adjudicate_the_session_they_proofed`** — the design asserts `assurance_score`, `granted_assurance_level` and a `decision` field. None exist in the PRD; the real fields are `adjudication_score` and `achieved_assurance_level`, and there is no persisted `decision`. Asserted the real names, substituting `adjudicator_user_id: None` + `adjudication_score: None` for the "no decision recorded" claim.
2. **`endpoints/address_change_opens_one_delivery_per_live_credential`** and **`calculations/exposure_index_...`** — dropped positional `data[0]/data[1]` ordering assertions where both rows are created at the same frozen logical instant, so "ascending `created_at`" does not uniquely order them; replaced with set equality over `credential_id` plus the design's own `delivery_count` discriminator.

No tests have been executed against a running implementation — the Step 6 implementation generator was still in flight.

**Orchestrator layout check:** `test_helpers/` and `test_suite/` both sit at the task root; no stray copies under `workspace/`.

## Step 6: Generate implementation — 2026-09-03T22:14:46.379Z

The implementation is complete, smoke-tested, and all test servers are shut down.

## Deliverable

`.../workspace/implementation/` — 22 files, 3,238 lines, no other artifacts (no `__pycache__`, no data files):

| file | lines | role |
|---|---|---|
| `start.sh` | 10 | launcher: guarded `pip install` (only if flask missing) then `exec python3 app.py`, honours `$PORT` (default 10000) |
| `requirements.txt` | 1 | flask |
| `app.py` | 68 | `create_app()`, 8 blueprints, ApiError/404/405/HTTPException/Exception handlers, `threaded=True`, `use_reloader=False` |
| `store.py` | 181 | in-memory `db` (plain dicts), logical clock, `base_row`, `touch`, `sort_rows` |
| `errors.py` | 107 | all 42 error ids → HTTP status + human default messages |
| `envelope.py` | 48 | `{meta, response_type, data}`, `req_` + 20 alnum id, 3-digit ms timestamps |
| `validate.py` | 223 | schema/type/enum/range/interval/pagination validation (400 ladder step 4) |
| `auth.py` | 56 | `endpoint()` decorator: header auth, role gate, global `RLock` serialisation |
| `gates.py` / `lookup.py` | 28 / 53 | ownership gates, FK resolution in declared order |
| `derive.py` | 156 | every `count(...)`/`sum(...)` recomputed from rows, never incremented |
| `calc.py` | 362 | 7 calculations: proofing score, revocation status, minimisation, exposure indices, invoice (Decimal ROUND_HALF_UP, per-line rounding), reissuance settlement, order rollup |
| `cascade.py` | 233 | 5-hop propagation, loss/recovery/wipe cascades, suspend/revoke, log-entry append with per-verifier salted pseudonym |
| `serialize.py` | 162 | per-entity projections incl. derived fields |
| `routes_*.py` (8 files) | 1,550 | 55 endpoints under `/mdl` |

Verified: all files `ast.parse` clean; 55 registered rules exactly matching SCAFFOLD.yaml (`MISSING: []`, `EXTRA: []`); grep audit confirms no sqlite/pickle/shelve/`json.dump`/`/tmp` — state is dicts only, nothing seeded (a fresh boot returns `total_count: 0` for every collection and 404 for every id).

## Smoke test

Three scenarios, each on a fresh process/port, then all killed by resolved PID via `/proc/net/tcp` inode → `/proc/*/fd` lookup (no pattern kill anywhere).

- **A (port 41874)** — full happy path: profile → snapshot → holder → device attest → proofing (4 evidence, submit, adjudicate, score 580/IAL2) → provision + activate → verifier approve → reader app + LIST → AGE_ONLY presentation (minimised to `['age_over_21']`), consent, disclose (billed 25), invoice `{25, 1 line, 0.0 surcharge}`, void-billing (balance 0, credited 25), address-change order → deliver (order COMPLETED, `resulting_doc_version` 2, credential doc 2 / `address_version_synced` 2), fail #1 → `UPDATE_FAILED`/ACTIVE, fail #2 → `STALE` + SUSPENDED/`UPDATE_FAILED` with exactly one ledger entry.
- **B (port 41875)** — snapshot tiling (overlap 409 / gap 422 / stale version 412 / exact tile 201), physical SUSPEND→VALID round trip, report-lost/recover, renew → `UPDATE_PENDING`, revoke → REVOKED seq 5 + replay 409, reissuance settlement 4050 cents with expedite, successor activation displacing predecessor to REPLACED with `reprovision_count` 1, validity overlap 409, stale device version 412, active-credential cap 409.
- **C (port 41876)** — privacy/trust surface: SoD 409, `ERR_VERIFIER_NOT_TRUSTED` before approval, duplicate serial 409, cert adjacency 422 vs +24h buffer 201, reader-not-trusted 403, surrender 422, LE-context 403, retention ceiling 422, ROUTINE soft withholding (`withheld: ['document_number','nickname']`, excess 2), consent negatives (403/400/422), DENY → `DENIED_BY_HOLDER` log with `pseudonym_reuse_index` 1 and exposure 12, disclose then replay 409, retention attestation re-scoring exposure to 36, REINSTATE 409 from APPROVED, void twice → `ERR_BILLING_ALREADY_VOIDED`, `BLOCKED_BY_POLICY` fork while an update is pending, clock jump → lazy EXPIRED + snapshot `revocation_pointer_stale` with 2 deltas, TERMINATE delisting LISTED apps, pagination 400.

Two notable behaviours that look surprising but are correct: an activate call with a wrong unlock proof returned `ERR_ACTIVE_CREDENTIAL_LIMIT_EXCEEDED` because ladder priority 26 (slot cap) precedes 28 (unlock proof); and publishing consecutive snapshots requires re-reading `version` because PRD §3.1 says every publication increments the profile version.

One environment note: two boot attempts hit "Address already in use" on ports in 45000–60000, which overlaps this host's ephemeral range (`32768 60999`) used by the other pipelines. Ports below that range work reliably — worth knowing when picking harness ports.

**Orchestrator note:** the impl generator reports "all 42 error ids" in `errors.py` while the PRD §5 catalogue has 43 rows. Left for Step 7 to surface if any test exercises the gap; not hand-patched here.

## Step 7: Run tests and iterate — 2026-09-03T22:36:06.989Z

All 8 rounds green — **103/103 passed in every round**, 0 failed, 0 errors.

## Summary

**Iterations run:** 2 (baseline sweep → fixes → confirming sweep).

**Iteration 1 baseline:** 89/103 passed, 14 failures — identical set in all 8 rounds, so zero flakiness. Two root causes, both test-side.

**Tests deleted:** none. Every failing test's rule was verbatim-covered by PRD and uniquely derivable; the defects were in the test artifact's translation, not in the rules.

**Fixes applied to `test_helpers/`:**

- `test_helpers/assertions.py` — added `parse_instant`, `instants_equal`, `_looks_like_instant` and `assert_instant`, and made `assert_field_values` compare ISO 8601 instants semantically instead of byte-wise. PRD §2.2/§2.4 pin three-fractional-digit rendering for exactly two fields (`api_request_timestamp`, `created_at`) and say nothing about the rendering of `closed_at`, `effective_at`, `lost_reported_at`, `assurance_expires_at`, `last_attestation_at`, `valid_from`, `valid_until`, `effective_from`/`effective_until` — only *which instant* each holds. 13 of the 14 failures were the implementation rendering `2026-08-01T00:00:00.000Z` where the test demanded the byte string `2026-08-01T00:00:00Z` for the same instant. Per STEP 1c partial-coverage handling, the PRD-covered part (the instant value) is kept and the non-derivable part (fractional-digit style) is dropped. No assertion was weakened — the instant is still asserted exactly.

**Fixes applied to `test_suite/`:**

- `test_suite/test_13_validation_rules.py` (`TestProvisioningAssuranceGates`) and `test_suite/test_08_resource_temporal_overlap.py` (`TestTrustListSnapshotsMustTileExactly`) — the 3 remaining direct `==` timestamp comparisons routed through `assert_instant` for the same reason.
- `test_suite/test_16_role_permissions.py` (`TestOperatorOwnership.test_an_operator_cannot_register_a_reader_app_for_another_verifier`) — the fixture built the second verifier with `category="FINANCIAL"`, which is not a member of PRD §3.7's enum (`COMMERCIAL`, `LAW_ENFORCEMENT`, `GOVERNMENT_SERVICE`, `AGE_RESTRICTED_RETAIL`). The PRD-faithful implementation correctly rejected the setup call with `ERR_INVALID_REQUEST` (400) before the test could reach its `ERR_NOT_RESOURCE_OWNER` assertion. Changed to `COMMERCIAL` (a bank), leaving the ownership assertion itself untouched.

**Fixes applied to `implementation/`:** none. No implementation defect was found — all 14 failures traced to the test layer, and no PRD-required check was removed or weakened.

Sweep artifacts left in place at `.../workspace/implementation/results.1.json` … `results.8.json`. No lingering runner or server processes; `__pycache__` cleaned.

**Orchestrator verification (independent, not taken on the subagent's word):** all 8 `results.$i.json` exist (~33 KB each, mtime 22:30) and each parses to `passed=103 total=103 failed=0 errors=0`. Sweep confirmed real.

**Step 8 skip decision:** NOT skipped. Step 7 applied 1 `test_helpers/` fix and 3 `test_suite/` fixes (0 deletions, 0 implementation fixes), so the skip condition (zero fixes of every kind) is not met. The timestamp-rendering item in particular is a genuine PRD silence the implementation resolved unilaterally.

## Step 8: Finalize PRD — 2026-09-03T22:46:32.365Z

Done.

## Line counts
- `PRD.md`: 500 lines
- `PRD_FINALIZED.md`: 502 lines (+2 lines, **+0.4 %**) — one inserted paragraph plus its blank separator; tail still ends inside the §5 Error Code Catalogue table.

## Changes
- **§2.4 Common Resource Properties and the Logical Clock** — *insert* — one new paragraph pinning the global instant-rendering convention: every instant-valued field in any response body (`created_at`, `updated_at`, §3 workflow instants, §4 projection instants, and the clock capability's `current_utc`) is serialised as an ISO 8601 UTC instant with **exactly three fractional digits** and a trailing `Z`, regardless of input precision or offset; a field holding no instant renders as `null`; the two calendar-date fields (`date_of_birth`, `physical_credential_expires_on`) render as `YYYY-MM-DD`. Impl: `implementation/store.py:80-89` (`iso()`), `implementation/serialize.py:136-143` (`_value`), `implementation/envelope.py:16-18`.

No other Step 7 item warranted a PRD edit (see below).

## Per-edit pre-edit search log

**Edit 1 — §2.4 instant rendering**
- **(a) Subject:** how the API renders instant-valued (and date-valued) fields in response bodies. Traced to the Step 7 `test_helpers/assertions.py` + `test_13`/`test_08` fixes, where 13 of 14 failures were impl emitting `2026-08-01T00:00:00.000Z` against a test demanding `2026-08-01T00:00:00Z` for the same instant, and PRD pinned three-digit rendering for only `api_request_timestamp` and `created_at`.
- **(b) Impl paths enumerated:**
  - `store.py:80-89` `iso()` — the single renderer; forces tz-aware, converts to UTC via `astimezone`, formats `%Y-%m-%dT%H:%M:%S.` + 3-digit ms + `Z`; returns `None` unchanged for `None` and passes non-datetimes through.
  - `serialize.py:136-143` `_value()` — the only projection path for persisted rows: `datetime → iso()`, `date → .isoformat()`, list copied, scalars passed through. `serialize.py:11-93` `FIELDS` read in full to enumerate every datetime-typed response field: `verified_at`, `assurance_expires_at`, `captured_at`, `lost_reported_at`, `valid_from`, `valid_until`, `activated_at`, `opened_at`, `closed_at`, `delivered_at`, `effective_at`, `last_attestation_at`, `cert_not_before`, `cert_not_after`, `effective_from`, `effective_until`, `published_at`, `listed_at`, `recorded_at`, plus `created_at`/`updated_at` tails — all funnel through `_value` (`dump`/`dump_many`, lines 146-162), so all get three digits.
  - `grep "iso("` across all of `implementation/` — only 5 callsites: `serialize.py:138`, `routes_profile.py:131` (`current_utc`), `routes_verifier.py:140` (`computed_at`), `routes_credential.py:271` (`effective_at` in the revocation-status projection), `routes_credential.py:236` (an instant embedded in an `UpdateOrder.payload_summary` *string*, not an instant-valued field).
  - `grep "return ok(" | grep -v serialize.dump` — confirmed the only 5 hand-built response dicts (`routes_profile.py:131`, `routes_proofing.py:108` assurance-preview, `routes_verifier.py:135` exposure-index, `routes_verifier.py:148` `calc.invoice`, `routes_credential.py:272` revocation-status); read `calc.invoice` (`calc.py:283-314`) and `calc.revocation_status` (`calc.py:131-167`) to confirm no raw `datetime` escapes un-`iso()`-ed. No leak found.
  - `grep "req_date|opt_date|req_dt|opt_dt"` across `routes_*.py` + `validate.py:117-157` — confirmed exactly two `date`-typed fields exist (`date_of_birth`, `physical_credential_expires_on`, both `routes_holder.py:42,48,85`), and that `parse_dt` normalises every inbound instant to UTC, which is what licences the "whatever precision or UTC offset ... on input" clause.
  - `grep` of PRD instant literals — only lines 44/69 (`api_request_timestamp` examples, already three-digit) and lines 97/452 (prose statements of the default clock *instant* `2026-08-01T00:00:00Z`, not rendering examples). Checked there is no `GET` clock endpoint whose response those lines could be read as pinning.
- **(c) Wording adjustments made:** (1) scoped the universal to *instant-valued fields in response bodies* rather than "all timestamps", so the `payload_summary` string at `routes_credential.py:236` and the §2.4/§4 prose clock literals are not mis-described; (2) added "A field that currently holds no instant is rendered as `null`" after confirming `iso(None) → None` and that `serialize.dump` always emits the key; (3) added the explicit calendar-date carve-out naming both `date` fields, since `_value` renders those with no time part; (4) added "whatever precision or UTC offset the value carried when a client supplied it on input" to cover the echo-back fields (`valid_from`, `cert_not_before`, `effective_from`, …) that `parse_dt` re-normalises; (5) enumerated the non-persisted carriers (`current_utc`, §4 projection instants) explicitly rather than saying "every persisted resource field", which would have left `computed_at` and the revocation-status `effective_at` unpinned.

**Considered and deliberately not edited — §3.7 verifier `category`**
- **(a) Subject:** the `category` enum on verifier registration (Step 7's `test_16` fixture fix from `FINANCIAL` → `COMMERCIAL`).
- **(b) Impl paths enumerated:** `routes_verifier.py:22` `CATEGORIES = ("COMMERCIAL", "LAW_ENFORCEMENT", "GOVERNMENT_SERVICE", "AGE_RESTRICTED_RETAIL")` and its use at `routes_verifier.py:37` via `v.req_enum`; `validate.py:53-59` `req_enum` → `bad_request` → `ERR_INVALID_REQUEST` (400); `routes_presentation.py:54-55` and `calc.py:176`, the only other readers of `verifier["category"]` (the `LAW_ENFORCEMENT` context gate).
- **(c) Adjustment:** none — no edit made. PRD §3.7 already lists exactly those four members verbatim, and §2.6 rung 3 already pins enum non-membership to `ERR_INVALID_REQUEST`/400, so the impl matches the PRD uniquely. This Step 7 item was a pure fixture bug, not a PRD silence.

**Fixes applied to `implementation/` in Step 7:** none, so no mismatch-driven edits were required.

**Orchestrator verification:** `wc -l` = 502 vs 500; `diff` shows exactly one inserted paragraph at line 95 plus its blank separator, no other hunks; tail still ends on the final §5 error row.

## Step 9: Complete PRD — 2026-09-03T23:45:49.319Z

**Orchestrator decision (recorded per AUTONOMY):** Step 9 was run as **three sequential file-partitioned passes** over one shared `PRD_COMPLETED.md` rather than one monolithic scan. A single-agent full scan of a 3,238-line, 22-file implementation against a 502-line PRD reliably degenerates into a near-no-op (the known failure mode is `PRD_COMPLETED.md` coming back byte-identical to its source). Partitioning by implementation file forces exhaustive coverage of every module and keeps each pass inside its context budget. Pass 1 created the file with `cp`; passes 2 and 3 were explicitly forbidden from `cp`/wholesale `Write` and edited in place, and each verified the prior passes' edits survived.

### Pass 1 — app/envelope/errors/store/validate/auth/gates/lookup/routes_profile/routes_holder/routes_device/routes_proofing

502 lines / 107,637 chars → 504 lines / 121,368 chars (+2 lines, +13,731 chars). **26 ambiguity-pins, 5 mismatch-revisions.** Headings byte-identical; tail intact.

- §2.1 — insert — ambiguity — whitespace-only auth headers rejected as empty — `auth.py:19-22`
- §2.1 — revise — **mismatch** — "a Holder may act only within its own `holder_id` chain" was false: ownership is compared only at the §2.6-step-6 operations; Holder-authorised reads/lists and handset registration do no comparison — `gates.py:21-23`, `routes_holder.py:74,159`, `routes_device.py:24,50`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `[A-Z0-9]` — `envelope.py:9-13`
- §2.2 — revise — **mismatch** — §2.4 claimed wall-clock is never consulted; `api_request_timestamp` is real server time, the sole non-logical-clock instant — `envelope.py:16-22`
- §2.2 — insert — ambiguity — the same two-key error `meta` serves 402/412 and any 5xx — `app.py:47-58`
- §2.3 — insert — ambiguity — empty query value = omitted; non-integer `limit`/`offset`, out-of-enum filter values, non-boolean boolean filters → `ERR_INVALID_REQUEST` at ladder step 3 (before the 404) — `validate.py:170-219`
- §2.3 — insert — ambiguity — `created_at` ties break by row-creation order, never by `id` — `store.py:131-132`
- §2.4 — insert — ambiguity — naive input instants read as UTC; sub-millisecond input **truncated**, not rounded — `validate.py:117-129`, `store.py:80-89`
- §2.4 — insert — ambiguity — clock endpoint returns `data.current_utc` and accepts instants earlier than the current reading — `routes_profile.py:126-131`
- §2.5 — insert — ambiguity — unrouted path → `ERR_NOT_FOUND`/404; wrong method → `ERR_NOT_FOUND`/**405**; neither passes through the ladder; trailing slashes tolerated — `app.py:27,38-45`
- §2.6 step 3 — insert — ambiguity — explicit `null` == absent; required strings non-empty; int/bool strict; unparseable/absent body → empty object; non-object body → 400; GET bodies ignored; the two uniqueness checks live here — `validate.py:13-99`
- §2.9 — revise — **mismatch** — `version` is per-**request**, not per-mutation: a row touched several times in one request rises by exactly 1 — `store.py:108-128`
- §3.1 — insert — ambiguity — duplicate `profile_code` → `ERR_INVALID_REQUEST` — `routes_profile.py:38-40`
- §3.1 — insert — ambiguity — `accepted_issuer_states` / `age_only_allowed_elements` members unvalidated — `routes_profile.py:26,36`
- §3.1 — insert (new paragraph) — ambiguity — "active profile" = most recently created `is_active` row (never cleared); with **no** profile the six jurisdiction defaults govern; "newest snapshot" = highest `snapshot_sequence`; pointer cascades skip what does not exist — `store.py:142-181`
- §3.2 — insert — ambiguity — duplicate `physical_credential_number` → `ERR_INVALID_REQUEST` — `routes_holder.py:52-56`
- §3.2 — insert — ambiguity — a new session's six adjudication fields all start null — `routes_proofing.py:42-48`
- §3.2 — insert — ambiguity — evidence append allowed only from `COLLECTING`/`RETURNED` (else `ERR_INVALID_STATE`); every append bumps the session's `version`; `captured_at` never compared to the clock — `routes_proofing.py:70-86`
- §3.2 — revise — **mismatch** — "every adjudication, whatever the decision, recomputes `superseded`" is wrong for a refused `VERIFY`: gates run first, rejected adjudications write nothing — `routes_proofing.py:149-153`
- §3.2 — insert — ambiguity — the missing-`return_reason` check is step 3, so it beats the session 404 — `routes_proofing.py:140-143`
- §3.2 — insert — ambiguity — the `VERIFIED → EXPIRED` lapse fires only on single-session read and provisioning, not on list or preview, and bumps `version` — `routes_proofing.py:57`, `routes_credential.py:51`
- §3.3 — insert — ambiguity — new handset nulls `attestation_result`/`secure_element_grade`/`lost_reported_at`; token opaque; a Holder may register under another `holder_id` — `routes_device.py:35-46`
- §3.3 — insert — ambiguity — `secure_element_grade` gates nothing anywhere, `SOFTWARE` included — `routes_device.py:61-75`
- §3.5 — insert — ambiguity — exact server-composed `payload_summary` wording for `ADDRESS_CHANGE` and `RESTRICTION_CHANGE`; `REVOCATION` is filter-only and never written; address-change returns HTTP 201 — `routes_holder.py:123-156`
- §3.6 — insert — ambiguity — loss cascade walks credentials `created_at` ASC; `PENDING_PROVISION` untouched — `routes_device.py:91-95`
- §3.6 — insert — ambiguity — `reattestation_token` only needs to be non-empty; unparsed, uncompared, unpersisted — `routes_device.py:102`
- §3.6 — insert — ambiguity — wipe revokes every `SUSPENDED` credential regardless of `suspend_reason`, `created_at` ASC, and aborts **no** presentation session (nor does loss, nor the physical branches — only explicit revocation does) — `routes_device.py:130-132`, `cascade.py:142-148`
- §3.6 — insert — ambiguity — all three PATCH fields optional (empty call still bumps holder `version`); returns the holder; `physical_credential_expires_on` drives no cascade; `EXPIRED`/`CANCELLED` drive none; intra-call order is expiry → status cascade → restrictions/order, so `REVOKED` + `restriction_codes` yields a zero-child `COMPLETED` order — `routes_holder.py:82-130`
- §3.6 — insert — ambiguity — the `VALID` reinstatement branch applies no `valid_until` and no cap test (unlike handset recovery) — `routes_holder.py:103-108`
- §3.6 — insert — ambiguity — all three status branches walk credentials `created_at` ASC — `routes_holder.py:95`
- §5 — revise — **mismatch** — the preamble claimed every failure carries a catalogued id; `ERR_NOT_FOUND` named as the one routing-level exception — `errors.py:69`, `app.py:38-45`

The no-new-mismatch rule caught and corrected two draft claims: an incorrect justification for why wipe aborts nothing, and an over-broad "unchanged rows never bump `version`" universal.

### Pass 2 — routes_credential/routes_update/cascade/derive

504 lines / 121,368 chars → 504 lines / 128,291 chars (+6,923 chars; all edits in-paragraph). **20 ambiguity-pins, 3 mismatch-revisions.** Pass 1's edits verified intact by spot-checking 8 distinctive pass-1 phrases, each present exactly once.

- §2.11 — insert — ambiguity — `credential_pseudonym` is a 32-char lowercase hex digest of a per-verifier server-minted salt plus the credential `id` — `cascade.py:66-68`
- §3.1 — insert — ambiguity — pointer hops bump the touched snapshot's *and* the profile's `updated_at`/`version` (invalidating an earlier `expected_interop_profile_version`); the reader-set hop leaves `revocation_pointer_stale` alone — `cascade.py:26-38`
- §3.4 gates — insert — ambiguity — session must be `VERIFIED`/`EXPIRED` to clear step 7 (other five states → `ERR_INVALID_STATE`); `REPLACED` predecessor → same code; unresolvable `supersedes_credential_id` → step-5 `ERR_CREDENTIAL_NOT_FOUND`, resolved last of four body FKs — `routes_credential.py:47-58`
- §3.4 result — insert — ambiguity — `suspend_reason`, `activated_at`, `protection_method_at_activation` all null on the fresh row — `routes_credential.py:96-100`
- §3.4 activation — revise — **mismatch** — conditions fire at ladder positions, not narrative order: step 6 → the two step-7 checks → step 17, and the slot cap (26) before the unlock proof (28); PRD previously read as "Finally the cap" — `routes_credential.py:154-186`
- §3.4 activation — insert — ambiguity — `active_credential_count` counts exactly `ACTIVE` credentials (and `revoked_credential_count` exactly `REVOKED`) — `derive.py:70-83`
- §3.4 activation — insert — ambiguity — `device_unlock_proof` validated only as a non-empty string, not against the protection-method enum, so a bogus value yields step-28 `ERR_PROTECTION_METHOD_MISMATCH`, not 400 — `routes_credential.py:150`
- §3.4 displacement — revise — ambiguity — predecessor's `suspend_reason` cleared to null; `reprovision_count` rises on the **new** credential's handset, the predecessor's older handset untouched — `routes_credential.py:208-216`
- §3.4 lazy expiry — insert — ambiguity — only single-credential read and presentation-open fire it; list/ledger/revocation-status/deliveries reads never do — `routes_credential.py:120-160`, `cascade.py:148`
- §3.5 renewal — insert — ambiguity — `new_valid_until` compared against nothing (not `valid_from`, not the old value, not the clock); the call returns the credential, not the order — `routes_credential.py:221-241`
- §3.5 payload summary — insert — ambiguity — renewal summary pinned as `Credential {id} validity extended to {instant}` with no closing full stop — `routes_credential.py:236`
- §3.5 hop 4 — revise — ambiguity — aborted sessions walked in ascending `created_at`, fixing hop-5 log order — `cascade.py:110-114`
- §3.5 zero-children — insert — ambiguity — an order closed by its own opening rollup is returned at `version` 2; one left `OPEN` at `version` 1 — `cascade.py:229-231`, `calc.py:334-341`
- §3.5 deliver — insert — ambiguity — `device_receipt_token` opaque, stored verbatim, never parsed — `routes_update.py:63`
- §3.5 deliver — insert — **mismatch** — the four gates fire in written order, putting step-17 `ERR_DEVICE_NOT_BOUND` ahead of the step-7 lifecycle check (contradicts the generic ladder) — `routes_update.py:73-82`
- §3.5 deliver — insert — ambiguity — the call returns the delivery row, not the order — `routes_update.py:105`
- §3.5 fail — insert — ambiguity — `ERR_DELIVERY_NOT_PENDING` is its only gate: no BOUND, lifecycle, or freshness check — `routes_update.py:112-120`
- §3.5 fail — revise — ambiguity — returns the delivery row — `routes_update.py:143`
- §3.5 second-failure — insert — **mismatch** — the lifecycle move and its ledger entry fire only if the credential is still `ACTIVE` (PRD claimed them unconditionally); `failed_delivery_count` is cumulative and never reset, so third-and-later failures — and the first failure of a new order — take this branch — `routes_update.py:124-141`, `derive.py:100-103`
- §3.6 wipe — insert — ambiguity — `active_binding_count` reads zero for a `WIPED` handset from then on, whatever rows remain — `derive.py:88-94`
- §3.7 — insert — ambiguity — `volume_discount_pct` is on the wire as `0.1`/`0.0`, not `10` — `derive.py:146-147`
- §3.8 fork — insert — ambiguity — `open_session_count` counts sessions of the verifier's apps in `REQUESTED`/`CONSENT_PENDING`/`CONSENT_GRANTED` — `derive.py:150-156`
- §3.8 log entries — insert — ambiguity — `retention_days_declared` is copied on **every** entry (blocked, denied, aborted), not only disclosures — `cascade.py:91`

### Pass 3 — calc/serialize/routes_verifier/routes_presentation

504 lines / 128,291 chars → 504 lines / 134,928 chars (+6,637 chars; all inline). **16 ambiguity-pins, 4 mismatch-revisions.** Verified programmatically that all 58 lines passes 1–2 had changed still differ from PRD_FINALIZED.md — zero regressions.

- §2.11 — insert — ambiguity — the per-verifier salt is minted at verifier creation and appears in no response body — `serialize.py:1,146-158`, `routes_verifier.py:53`
- §3.1 — revise — **mismatch** — the reader-set pointer hop fires only from the `LIST`/`DELIST` endpoint; a `TERMINATE`-driven delisting moves neither counter — `routes_verifier.py:99-104` vs `:248`
- §3.2 — insert — ambiguity — a `captured_at` tie that is *also* a `created_at` tie resolves to the earlier-created item — `calc.py:99-101`
- §3.5 — insert — ambiguity — the rollup touches the order only when it actually moves `status` or stamps `closed_at` — `calc.py:334-341`
- §3.6 — revise — ambiguity — **handed-over item (i)**: the revocation-status projection is exactly six fields — `credential_id`, `status`, `entry_sequence`, `effective_at` (null when no entries), `staleness_seconds`, `is_fresh`; staleness is floored and *signed*, not clamped — `calc.py:160-167`, `routes_credential.py:270-272`
- §3.7 — insert — ambiguity — `purpose_scope` validated only as an array of strings, members never checked against the core element set — `routes_verifier.py:38`
- §3.7 — insert — ambiguity — `last_attestation_at` / `attested_max_retention_days` start null — `routes_verifier.py:48-49`
- §3.7 — insert — ambiguity — `PROBATION` accepted only from `APPROVED`, `PROBATION` itself included in the refusal — `routes_verifier.py:76-79`
- §3.7 — revise — **mismatch** — `TERMINATE` aborts in-flight sessions of **every** reader app of the verifier, not only the ones it delisted; apps and their sessions walked in `created_at` order; delistings fire no pointer hop — `routes_verifier.py:99-104`
- §3.7 — insert — ambiguity — list-decision has no state gate: `LIST` of a `LISTED` app restamps `listed_at`, `DELIST` of a `PENDING` app is accepted — `routes_verifier.py:240-245`
- §3.8 — insert — ambiguity — `retention_days` is a step-3 integer ≥ 0 with no schema maximum — `routes_presentation.py:38`
- §3.8 — insert — ambiguity — both minimisation arrays are de-duplicated (first occurrence wins); `age_attestation_only` is vacuously true on an empty `minimized_elements` — `calc.py:185-200`
- §3.8 — insert — **mismatch** — the step-7 lifecycle check runs *below* the step-13…31 business gates on this path, resolving the tension with §2.6 — `routes_presentation.py:50-80`
- §3.8 — insert — ambiguity — a created session returns at `version` 1 on **both** fork branches, unlike the zero-child order of §3.5 — `routes_presentation.py:82-113`
- §3.8 — insert — ambiguity — consent `unlock_method` is a free non-empty string checked at step 28, and the conditional requirement precedes the 404 — `routes_presentation.py:144-146`
- §3.8 — insert — ambiguity — disclose's gate stack is closed: neither credential axis nor verifier `trust_status` is re-consulted; balance weighed pre-billing — `routes_presentation.py:187-197`
- §3.8 — revise — ambiguity — the rolling-window index is recomputed over a log that already contains this disclosure's own entry — `routes_presentation.py:206-216`
- §3.9 — insert — ambiguity — `attested_max_retention_days` is ≥ 0 with no upper bound (not capped at the contract or 90) and no trust-status gate guards attestation — `routes_verifier.py:111-126`
- §3.9 — revise — ambiguity — **handed-over item (ii)**: invoice returns exactly four fields and `surcharge_pct` rides the wire as the fraction `0.15`/`0.0`, mirroring `volume_discount_pct` — `calc.py:308-314`
- §4 `GET /verifiers/{id}` — revise — **mismatch** — "live exposure index" was wrong; `exposure_index` is stored, written only by the two §3.9 variants — `serialize.py:62-68,127-132`

### Step 9 totals and orchestrator verification

62 pins/revisions across the three passes (62 ambiguity-pins + 12 mismatch-revisions counted per pass: 26+5, 20+3, 16+4). Final `PRD_COMPLETED.md`: **504 lines / 134,928 chars**, versus `PRD_FINALIZED.md` at 502 / 107,637 — a **+27,291 char (+25.4 %)** elaboration, 60 changed/added lines. Independently verified by the orchestrator: the file is not byte-identical to its source (so the scan really ran), the heading set is byte-identical to `PRD_FINALIZED.md` (no new sections), and the tail still ends on the final §5 row `| ERR_VERIFIER_ACCOUNT_DELINQUENT | 402 |`.

No sweep re-run was needed after Steps 8–9: both steps write only PRD derivative documents and touch neither `implementation/` nor the test tree, so the verified 8×103/103 result from Step 7 remains the standing evidence.

**PIPELINE COMPLETE.**

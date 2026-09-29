# Worklog — task_2569_earnings_disclosure_committee_process

## Step 1: Create task directory — 2026-09-03T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2569_earnings_disclosure_committee_process` and `.../workspace` (index pre-assigned by orchestrator invocation; no ./tasks/ scan performed, per instructions).

## Step 2: Generate Scaffold — 2026-09-03T17:40:59.000Z

All three artifacts are complete, lint-clean, and audited.

## Files

| Path | Lines |
|---|---|
`/home/ubuntu/github/CodingPRD/tasks/task_2569_earnings_disclosure_committee_process/SCAFFOLD.yaml` | 3027 |
`/home/ubuntu/github/CodingPRD/tasks/task_2569_earnings_disclosure_committee_process/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2733 |
`/home/ubuntu/github/CodingPRD/tasks/task_2569_earnings_disclosure_committee_process/SCAFFOLD_CORNER_DESIGN.yaml` | 5649 |

## Counts

- **§1.1–§1.7:** 14 entities, 15 state-machine blocks (ReportingCycle carries two parallel axes: `status` × `restatement_stage`), 16 calculations, 2 concurrency rules, 45 validations, 52 endpoints, 57 error codes, 7 roles.
- **complexity_profile:** compliance_audit + multi_party_negotiation, layers [optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers], graph topology, parallel state shape, role_model segregation_of_duties, consistency immediate, difficulty `expert_plus`.
- **§1.8:** 23 instances over all 9 rule_ids — [2,3,2,3,3,3,3,2,2].
- **§1.9:** 66 instances over all nine guide sections (entities 11, state_machines 14, calculations 13, validations 8, endpoints 4, errors 6, rbac 4, complexity_layers 5, consistency_model 1) = 50 full `test_recipe`s + 16 `excluded_because` stubs. 1288 API calls total across both design files; 77 unique instance names, zero collisions.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2569_earnings_disclosure_committee_process/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2569_earnings_disclosure_committee_process/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2569_earnings_disclosure_committee_process/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     14
  §1.8 instances scanned:     23
  §1.9 instances scanned:     50
  Calls scanned (§1.8+§1.9):  1288

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Design adjudications (11)

1. QandAItem create seeds `BLOCKED` for HIGH `risk_tier` or `requires_safe_harbor`, else `DRAFT` — makes the `BLOCKED→CLEARED` edge reachable.
2. Document drafting/SUBMIT_REVIEW admitted on a `FILED` cycle so the amendment path is reachable.
3. `ERR_DEFICIENCY_OPEN` gated on the *amending* Filing, not the original.
4. Pagination `max: 200` pinned in the envelope so the bounds corner has a hard edge.
5. Priority 33 (`ERR_MILESTONE_MISSING`) gates `OPEN_CLOSE` on a CLOSE milestone, resolving a §1.2/§1.4 disagreement.
6. Priority 12 (`ERR_ENTITY_TERMINAL`) explicitly excludes ControlDeficiency, whose terminals are reported by `ERR_DEFICIENCY_ALREADY_MITIGATED` at 38 (un-masks 38).
7. Priority 13 dropped a redundant mitigation parent gate.
8. ABANDON cascade extended to MaterialEvent → `SUPERSEDED`, fixing a §1.2 inconsistency.
9. Priority 24 realigned with §1.1's `qa_gate_status` plus an explicit readiness-ordering note.
10. Added the `AMENDED → AMENDED` self-edge, making `ERR_AMENDMENT_TARGET_INVALID` reachable.
11. Scope-of-target note on priority 12: the target is the path-named row plus the parent a create writes into — never a row merely *referenced* by a body field, so a superseded `amends_filing_id` reports `ERR_AMENDMENT_TARGET_INVALID` (priority 37), not `ERR_ENTITY_TERMINAL`.

## Final-pass fixes made in this closing audit

- Normalized 13 `grounds:` refs in §1.9 to the canonical dot form the spec's schema shows (`calculations.X`, `state_machines.<Entity>.<FROM>_to_<TO>`, `entities.<Entity>.fields.<name>`, `response_envelope.pagination_defaults`); all 100+ grounds now resolve mechanically.
- Added the required `name:` (12) and `grounds:` (16) keys to every `excluded_because` stub — the spec mandates `name` + `claim_type` + `grounds` + `excluded_because`, and they were previously `claim_type` + `excluded_because` only.
- §1.2 DraftDocument `→ SUPERSEDED` edge now declares its second, system-triggered path (owning cycle ABANDONED) alongside the create-with-supersede path, so the ABANDON cascade side-effect is captured on both ends.

Audits that came back clean without changes: placeholder closure (0 unbound across both files), OCC literal discipline, §1.4 `http_status` vs §1.6 (0 mismatches), endpoint roles ⊆ §1.7 (and every role used), both concurrency rules require `expected_*_version` and bump the parent version, enum-value closure, forbidden concurrency vocabulary (0 hits), no `id`-based ordering in business decisions, and a re-simulated replay of the milestone RULE A/B/C calendar, sub-certification due-window, uniqueness, prep-window capacity and SoD gates over every chain in both files (all flags proved to be intentional negative legs or WITHDRAW-freed slots).

## Step 3: Copy Shared Files — 2026-09-03T17:40:59.000Z

Copied `INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T18:02:00.000Z

PRD generation complete and verified.

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_2569_earnings_disclosure_committee_process/workspace/PRD.md` — **525 lines**, ~15.6k words, built incrementally via 13 heredoc appends + 2 edits, each confirmed with `wc -l`/`tail`. Ends at a real boundary (last row of the §5 error table); no audit footer, no truncation.

**Section list**
- §1 Introduction
- §2 Global Specifications: 2.1 Committee Seats, Roles and Request Authentication · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Common Record Properties · 2.5 Numeric Precision, Basis Points and Rounding · 2.6 The Logical Clock and the Business-Day Calendar · 2.7 Path Resolution and Referential Validation Order · 2.8 Optimistic Concurrency on Parent Records · 2.9 Terminal Records and Transition Legality · 2.10 Segregation of Duties · 2.11 The Order in Which Rules Fire · 2.12 Cascades, Conserved Roll-Ups and Recomputation Discipline
- §3 Business Logic & Workflows: 3.1 Charters and Seats · 3.2 Opening a Cycle and Fixing Its Deadlines · 3.3 Windows, Buffers and Slack · 3.4 Sub-Certifications · 3.5 Drafting and Reviewing Documents · 3.6 Tie-Out · 3.7 Adjusted Measures, Prominence and the Q&A Bank · 3.8 Material Events, Officer Certification and the Filing-Readiness Gate · 3.9 Filing, Amendment, Correction and Restatement Remediation
- §4 Endpoint Definitions (52 rows, 4 columns)
- §5 Error Code Catalogue (57 rows, 2 columns)

**Hard Contract 1 — Field-Name Coverage: PASS.** Mechanically extracted 129 required identifiers (114 entity fields + body inputs + query params + computed-read output shape + pagination fields) and diffed against backticked tokens (two passes; first pass found `correction_id` missing, now fixed in §3.9). Also verified: 57/57 error ids, 7/7 role names, and every enum value of every enum field appear verbatim in backticks.

**Hard Contract 2 — Rule Coverage: PASS.** Validation priority ordering: all 45 rules rendered as an explicit numbered ladder in §2.11 with their `applies_to` scopes and error ids, plus the two named masking consequences (rule 17 before 18; rule 42 before 43). OCC: both rules in §2.8. Cross-entity side effects: the VACATE 4-hop, ABANDON 4-way, tie-out 5-hop (ending in `REVOKED` certifications with `coverage_pct_at_signing` retained), material-event/certification two-way gate, correction ASSESS 4-hop, RESCIND 4-hop compensation, and mitigate chain all rendered hop by hop. Field-level structured content: `reconciliation_items` objects (`label`, `amount`). Sibling-branch symmetry: clean vs exception SUBMIT, ACCEPT vs WAIVE, REPORTABLE vs NOT_REPORTABLE, ROLLOVER vs IRON_CURTAIN (with the 4.00-REVISION vs 5.83-RESTATEMENT divergence on identical data), original vs amending filing. Verified programmatically that every state name from all 15 state axes and all 20 `action` tokens appear verbatim; added a §2.1 paragraph giving the complete action vocabulary per endpoint (`REINSTATE` was the only token missing). All 16 calculations narrated in prose with their constants; zero pseudocode, zero fuzzy words, and the 20 arrows were rewritten as "from X to Y" prose.

**Hard Contract 3 — §3 Path Purity: PASS.** 305 distinct backticked tokens in §3; none starts with `/`, none is a bare HTTP method, none is a method+path pair. No raw `/disclosure` string and no verb+path string appears anywhere in §3.

Also confirmed: §2.2 is byte-identical to `section-2.2-response-structure.md`; the §4 table's (method, path) set exactly matches the scaffold's 52 endpoints; the §5 table matches the scaffold's 57 errors in the same order with the same statuses; §3 contains no tables. The two withheld design files were never opened or referenced.

**Orchestrator truncation check**: `tail -12 PRD.md` ends on the final error-table row `| ERR_MILESTONE_SLACK_EXHAUSTED | 409 |` — a real section boundary, not mid-sentence. Grep for the difficulty instruction ("harder than expert", "expert level", "scaffold") in PRD.md returns zero hits, so the Step-2-only difficulty directive did not leak. No regeneration needed.

## Step 6: Generate Implementation — 2026-09-03T18:35:00.000Z

Implementation complete and verified.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2569_earnings_disclosure_committee_process/workspace/implementation/`:

| File | Lines | Role |
|---|---|---|
| `start.sh` (executable) | 9 | `exec python3 app.py`, `PORT` default 10000, guarded pip install |
| `requirements.txt` | 1 | `flask==3.0.3` |
| `app.py` | 62 | blueprint registration, `ApiError`/`HTTPException` handlers, `0.0.0.0:$PORT`, **no seeding** |
| `core.py` | 417 | 58-id error catalog + HTTP map, 45-rule ladder table, logical clock (startup `2026-08-01T00:00:00Z`), Decimal helpers, business-day calendar (9 holidays), empty in-memory `Store` (14 tables), response envelope, `TouchLog` version-bump primitive |
| `validate.py` | 176 | body/field/enum/instant coercion, pagination (1-200 / offset >= 0), query filters |
| `authz.py` | 145 | `X-User-ID`/`X-User-Role`, 7 roles, seat resolution + function gates, action->role matrix |
| `calc.py` | 543 | every derived quantity: deadlines, slack, breach sweep, scope weights, coverage, 5-step tie-out derivation + 5-hop cascade, measure reconciliation, QA gate, event severity, correction materiality (both methods), deficiency scoring, accession labels, readiness blockers |
| `helpers.py` | 27 | sort orders + paging |
| `routes_charter.py` | 212 | 8 endpoints |
| `routes_cycle.py` | 354 | 8 endpoints |
| `routes_cert.py` | 297 | 8 endpoints |
| `routes_doc.py` | 484 | 14 endpoints |
| `routes_event.py` | 184 | 4 endpoints |
| `routes_filing.py` | 370 | 9 endpoints |
| `routes_clock.py` | 17 | 1 endpoint |

3298 lines total; every `.py` passes `py_compile`.

## Endpoints
**52 implemented = 25 GET + 27 POST**, exactly matching the scaffold table (enumerated from Flask's url_map, excluding `/static`). Storage is dicts only; nothing is seeded at import or boot.

## Verification
`bash start.sh` boots, binds `0.0.0.0`, answers 200. A full end-to-end smoke run (charter -> members -> adopt -> cycle -> 4 milestones -> subcert -> tie-out -> document approval -> certification open -> 2 officer signatures -> filing-ready -> filing -> correction -> deficiency -> mitigation -> material event -> 8-K disclosure -> adjusted measure -> Q&A clearance, plus 401/403/404/412/422 paths) reported **0 failures**. Spot-checked numerics matched the PRD's worked examples: iron-curtain `5.83 / RESTATEMENT` vs rollover `4.00 / REVISION` on the same row; `MATERIAL_WEAKNESS` score `5.83`, weight `23.32`; compensated case `2.40 -> SIGNIFICANT_DEFICIENCY -> 4.80`; accession `FORM_10Q-2026-Q2-1`; tie-out tier flip to `0.5` with `effective_tolerance_bp = floor(10 x 0.5) = 5`, the 5-hop cascade driving an `APPROVED` document to `CHANGES_REQUESTED` with `change_note = "auto: tie-out variance detected"`, and a waive relaxing the tier back to `1.0` while keeping the waived row's `raw_variance_bp` frozen at 10000. Readiness returns all 15 declared fields with `blocking_error_ids` ladder-ordered. Smoke server was killed by its own recorded port/PID only; no broad pkill was used.

## PRD ambiguities resolved
1. **Not-found id for officer certifications** — catalog uses `ERR_OFFICER_CERT_NOT_FOUND` (not `ERR_CERTIFICATION_NOT_FOUND`); adopted the catalog spelling.
2. **Rule 30 scope** — ladder rule 30 says "no unresolved deficiency weight **and is not mid-restatement**", §3.9 says weight only for amending filings. Chose: `DECLARE_FILING_READY` enforces both clauses; the **amending filing** enforces weight only (§3.9 is the specific prose for that write).
3. **Version-bump dedup** — a row touched both as a create's parent and by a cascade rises by exactly 1 (`TouchLog` dedups per row per request), since the scaffold restates the same increment at endpoint and state-machine level.
4. **Terminal-target scope (rule 12)** — targets are the path-named row plus creation parents whose *version increments*. So creating a cycle against a `SUPERSEDED` charter yields `ERR_CHARTER_NOT_ADOPTED`, and an amendment pointing at an `AMENDED_SUPERSEDED` filing yields `ERR_AMENDMENT_TARGET_INVALID` (referenced, not target), while a `FILED` document on `POST /filings` yields `ERR_ENTITY_TERMINAL`.
5. **Event determination floor** — scaffold demands a >=20-character `determination_note` on sub-5.00% `REPORTABLE` assessments; PRD says "There is no corresponding floor on the `REPORTABLE` branch". Followed the PRD: only the >=5.00 -> cannot-be-`NOT_REPORTABLE` rule is enforced.
6. **Tie-out item version bumps** — only items whose *status* changes bump `version`; a mere `effective_tolerance_bp` shift does not, and the just-created row is exempt.
7. **Tie-out `line_label` uniqueness** — enforced as `ERR_INVALID_REQUEST` but checked *after* OCC/state/seat, so a resubmitted identical payload still returns `ERR_STALE_DOCUMENT_VERSION` (412). Verified a duplicate label is accepted once the prior row is `WAIVED`.
8. **QA items on non-`CALL_SCRIPT` documents** — no error id is declared for the doc_type restriction, so it is not enforced.
9. **Breach-sweep placement** — runs after transition legality (rule 13) and before action gates, so a failed transition still sweeps/recomputes slack but does not bump the cycle version; the readiness GET sweeps without bumping the cycle.
10. **`ASSESS` shape vs state ordering** — the three deficiency inputs become required once the computed classification is non-immaterial, so materiality is computed first and rule 8 is enforced before rules 12/13, per §2.11's ladder.
11. **Sign-time ordering** — normative §2.11 order (open events 28 -> scope-empty 42 -> coverage 43) with the officer-subcert SOD check last.
12. **Unrouted paths** — 404/405 return the standard envelope with a synthetic `ERR_NOT_FOUND` (no declared id exists for unknown routes).

## Step 5: Generate Unit Tests — 2026-09-03T20:41:00.000Z

All 18 test modules are complete and verified. Final state:

**test_helpers/** (Stage 1, unchanged this session)
- `__init__.py` 33, `api_client.py` 463, `api_errors.py` 132, `assertions.py` 140, `constants.py` 253, `factories.py` 241, `fixtures.py` 1035, `test_users.py` 104, `types.py` 215

**test_suite/** (Stage 2)
- `conftest.py` 26
- Queue A (Difficulty): `test_01` 220 (4), `test_02` 307 (6), `test_03` 185 (4), `test_04` 316 (6), `test_05` 277 (6), `test_06` 282 (7), `test_07` 363 (8), `test_08` 234 (4), `test_09` 221 (4) — **49 tests**
- Queue B (Corner): `test_10_entity_records` 661 (11), `test_11_lifecycle_states` 754 (10), `test_12_computations` 598 (8), `test_13_validation_gates` 424 (5), `test_14_endpoint_behaviour` 567 (8), `test_15_error_catalogue` 1069 (16), `test_16_access_control` 535 (6), `test_17_concurrency_tokens` 301 (4), `test_18_derived_field_visibility` 259 (5) — **73 tests**

Total **122 tests**. New this session: `test_18_derived_field_visibility.py`, 5 tests for the single live `consistency_model` instance (derived `scope_weight` in the creating response + empty-numerator coverage 0.00 over a 55.00 scope; midway 54.55 -> 100.00 with a conserved total and a status-filtered list that is as fresh as the by-id read; a HIGH question flipping the parent script's `qa_gate_status` to BLOCKED inside its own creating request; clearance releasing it; a logged event scoring 8.00/UNASSESSED and raising the grandparent cycle's `open_material_event_count` to 1).

**Verification (whole suite, run just now)**
- Design-index cross-check against both yamls: 73 live instances, **all 73 covered**, 0 excluded (`excluded_because`) stubs translated, 0 orphan tags, exactly one `Design:` line as the last docstring line on every test (multiplicity 1-5).
- Every `PRD x.y: "..."` citation is a literal substring of `workspace/PRD.md`; zero occurrences of the word "scaffold"; the section symbol appears only in the two deliberate 2.11 `blocking_error_ids` citations (test_14, test_15).
- `ast.parse` and `python3 -m py_compile` pass on all 28 generated .py files; `pyflakes` clean except the intentional `# noqa: F401` fixture re-exports in `test_suite/conftest.py`.

**Instances SKIPPED: none.** No live instance failed the PRD-first filter. The 16 `excluded_because` stubs (5 calculations, 4 state_machines, 3 validations, 3 cross_cutting_complexity_layers, 1 rbac) were left untranslated by contract. One partial translation, deliberate and not weakened: `Corner/errors/filing_readiness_and_amendment_guards_fire_in_sequence_on_a_single_cycle` — its fourth sub-claim (a third filing rejected with `ERR_AMENDMENT_TARGET_INVALID`) is unreachable through declared endpoints, because document creation is gated to `CLOSE_OPEN`/`REVIEW_OPEN`/`FILED`, so no APPROVED `PERIODIC_FILING` can exist once the cycle is `AMENDED`, and rule 36 (`ERR_FILING_DOCUMENT_INVALID`) fires before rule 37. The three reachable claims (certs-gate beats slack-gate, slack recovery on completing the tight window, `ERR_DEFICIENCY_OPEN` -> mitigation -> Amendment No. 1) are all asserted.

## Step 7: Run Tests and Iterate — 2026-09-03T20:24:00.000Z

Clean sweep. Cleanup verified — no stray debug servers, no temp artifacts.

## Summary

**Iterations run:** 2 (one 8-round parallel sweep each).

**Tests deleted:** none. Both failures traced to test-side defects that were fixable toward *greater* PRD fidelity, so no test failed the STEP 1 coverage / unique-derivability filter. Test count is still 122.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` -> `log_material_event()`: added an `actor` selector (`"counsel"` default, `"admin"`). The helper previously hard-wired `committee.counsel(counsel_key)`, i.e. it stamped `X-User-Role: LegalCounsel` onto whatever seat it was handed. PRD 2.1 states "`LegalCounsel` requires `LEGAL`", and PRD 4 authorises the material-event endpoint for **`ComplianceAdmin`, `LegalCounsel`** — so a roster with no LEGAL seat must log as the opaque admin credential, which the helper had no way to express.

**Fixes applied to `test_suite/`:**
- `test_04_cascades.py` -> `test_the_same_break_drops_the_cycle_out_of_filing_ready_and_revokes_both_signatures`: expected error changed from `ERR_FILING_DOCUMENT_INVALID` to `ERR_INVALID_STATE` (both 409, so still an exact `error_id` assertion — not a downgrade). The tie-out cascade has already pulled the cycle from `FILING_READY` to `REVIEW_OPEN` (the test asserts this two lines earlier), and PRD 3.9 says "An **original filing** omits `amends_filing_id` and is legal only from `FILING_READY`". 2.11 puts the transition-legality rule at **13** and the document-class rule at **36**, and "a lower number always wins" — so the ladder uniquely determines `ERR_INVALID_STATE` here. Added the 3.9 citation plus an inline note on the 13-before-36 precedence.
- `test_11_lifecycle_states.py` -> `test_six_machines_read_their_declared_initial_state_at_birth`: `counsel_key="fin"` -> `actor="admin"`. Its `BIRTH_SEATS` roster is two FINANCE seats with no LEGAL member, so the old call asked a FINANCE seat to act as `LegalCounsel` and the PRD-faithful implementation correctly answered `ERR_MEMBER_FUNCTION_MISMATCH` (403).

**Fixes applied to `implementation/`:** none. `routes_filing.py::create_filing` was already ladder-faithful (terminal 12 -> state 13 -> document 36 -> amendment 37 -> certifications 44), and `authz.py`'s function gate was correctly enforcing 2.1. No implementation check was removed or weakened.

**Final sweep, per-round (quoted from `workspace/implementation/results.$i.json`):**

| round | passed/total | failed | errors | skipped | duration |
|---|---|---|---|---|---|
| 1 | 122/122 | 0 | 0 | 0 | 225.6s |
| 2 | 122/122 | 0 | 0 | 0 | 225.5s |
| 3 | 122/122 | 0 | 0 | 0 | 225.5s |
| 4 | 122/122 | 0 | 0 | 0 | 225.5s |
| 5 | 122/122 | 0 | 0 | 0 | 225.6s |
| 6 | 122/122 | 0 | 0 | 0 | 225.6s |
| 7 | 122/122 | 0 | 0 | 0 | 223.8s |
| 8 | 122/122 | 0 | 0 | 0 | 225.5s |

Union of failing tests across all 8 rounds: **empty**. Both original failures were deterministic (8/8 rounds, identical message), not load-induced — the interleaved `PASSED`/`FAILED` counts in `sweep.log` were just concurrent rounds writing to one log, which the per-round results files disambiguated.

**Orchestrator independent verification**: re-read all 8 `results.$i.json` from disk (timestamps 20:23, ~36.8 KB each) — every file reports `passed=122, total=122, failed=0, errors=0`. Sweep artifacts confirmed present; not taken on the subagent's word.

## Step 8: Finalize PRD — 2026-09-03T20:36:00.000Z

Done. One PRD edit was warranted; the other two Step 7 items were pure fixture/test defects already uniquely determined by PRD.md.

## Line counts
- `PRD.md`: 525 lines — `PRD_FINALIZED.md`: 525 lines (0.00% delta; 1 line revised, no lines added or removed).

## Changes
- **2.9 (parent-state gates / transition legality)** — revise — added filing creation to the enumeration that ladder rule 13 normatively cites: a cycle admits an original filing (no `amends_filing_id`) only while `FILING_READY`, and an amending filing only while `FILED` or `AMENDED`, and a state violation is reported at rule 13 ahead of the rule-36 document-class check and every later gate on that endpoint — `implementation/routes_filing.py:90-96` (state), with the following gates at `:93` (30), `:98` (36), `:107` (37), `:112` (44).

Traceability: this is the `test_04_cascades.py::test_the_same_break_drops_the_cycle_out_of_filing_ready_and_revokes_both_signatures` fix (`ERR_FILING_DOCUMENT_INVALID` -> `ERR_INVALID_STATE`). PRD.md rule 13 says "as enumerated in 2.9", but 2.9's enumeration never mentioned filing creation, while 3.9's prose introduces the `ERR_FILING_DOCUMENT_INVALID` document-class rule *before* the "legal only from `FILING_READY`" rule — which is exactly the reading the original test took. Impl checks state first.

## Per-edit pre-edit search log

**Edit 1 — 2.9 filing-creation state gate**
- (a) Subject: which cycle workflow states admit a filing creation, and where that refusal sits relative to the endpoint's other gates.
- (b) Impl paths enumerated: `routes_filing.py::create_filing` (read in full — terminal cycle `ABANDONED` / document `FILED|SUPERSEDED` at rule 12, amending state gate `FILED|AMENDED`, original state gate `FILING_READY`, then `ERR_DEFICIENCY_OPEN`, `ERR_FILING_DOCUMENT_INVALID`, `ERR_AMENDMENT_TARGET_INVALID`, `ERR_CERTIFICATIONS_INCOMPLETE`); grepped all of `implementation/*.py` for `new_row("filing"`, `FILING_READY`, `"AMENDED"`, `ERR_INVALID_STATE` and `ERR_FILING_DOCUMENT_INVALID` to find every other path touching filing rows, cycle filed/amended states, or the same two error ids — hits confirmed as unrelated parallel gates: `routes_cycle.py:149-173` (`DECLARE_FILING_READY` from `CERTIFICATION_OPEN`), `routes_cycle.py:201` (`OPEN_CERTIFICATION`'s approved-`PERIODIC_FILING` check), `routes_cert.py:176` (subcert withdrawal blocked from `FILED`/`AMENDED`), `routes_event.py:172` (disclosure's `CURRENT_REPORT` check), `calc.py:311` (tie-out cascade's `FILING_READY` hop), `calc.py:477-543` + `routes_cycle.py:139` (readiness dashboard `blocking_error_ids`, which scopes itself to a `DECLARE_FILING_READY`), `validate.py:23` (`present()` treats explicit null as absent), `core.py:82` (`LADDER_PRIORITY["ERR_INVALID_STATE"] == 13`). `create_filing` is the only filing-creation path.
- (c) Wording adjustments made: (i) scoped the new clause to the cycle only and phrased it as two branches keyed on `amends_filing_id` rather than a single "filing creation requires `FILING_READY`" claim, so the amending path (`FILED`/`AMENDED`, and repeat amendments staying in `AMENDED`) is not mis-described; (ii) said the state refusal sits "ahead of the document-class check of rule 36 and of every later gate on that endpoint" instead of "ahead of every other check", so the earlier rules the impl really does evaluate first (path/body FK resolution, request shape, and the rule-12 terminal checks on the `ABANDONED` cycle and the `FILED`/`SUPERSEDED` document) remain intact; (iii) reused PRD.md's existing "omits / supplies" phrasing for `amends_filing_id` rather than introducing "non-null", leaving the explicit-null edge exactly as under-determined as it already was.

**Non-edits (Step 7 items that needed no PRD change)**
- `test_helpers/fixtures.py::log_material_event` actor selector, and `test_11_lifecycle_states.py` `counsel_key="fin"` -> `actor="admin"`. Subject: authorisation of `POST /disclosure/reporting-cycles/{id}/material-events`. Paths enumerated: `authz.py::authorize` (rules 1-4: `endpoint_has_seat_role and role != ComplianceAdmin` gates seat resolution, `_function_gate_ok` requires `function == "LEGAL"` for `LegalCounsel`), `routes_event.py` create route's role list, PRD 4 row for that path. PRD.md 2.1 ("`LegalCounsel` requires `LEGAL`", `ComplianceAdmin`'s id is opaque and never resolved to a seat) plus 2.11 rules 3 and 4 ("the opaque `ComplianceAdmin` role is exempt") already determine both the 403 `ERR_MEMBER_FUNCTION_MISMATCH` the old fixture provoked and the admin-credential path it lacked. Pure fixture defects — no PRD silence, no edit.
- No `implementation/` fixes and no test deletions occurred in Step 7, so nothing else in scope.

## Step 9 (pass 1 of 3): PRD completeness scan — core/validate/authz/charter — 2026-09-03T20:50:00.000Z

Orchestrator note: per the known failure mode where a single-shot Step 9 returns a PRD_COMPLETED.md byte-identical to its source (i.e. the scan never ran), Step 9 was split into three sequential file-partitioned passes over `implementation/`. Pass 1 creates the file; passes 2 and 3 edit it in place.

Pass 1 of 3 complete.

## Output file
- Created `workspace/PRD_COMPLETED.md` as a copy of `workspace/PRD_FINALIZED.md`, then edited only that file.
- Source: 525 lines / 114,132 bytes. Output: 526 lines / 118,271 bytes. Delta: +1 line, +4,126 characters (+4,139 bytes). The single new line is the `ERR_NOT_FOUND` row appended to the 5 catalogue table; every other change is an in-paragraph insert or revision. No new sections.

## Counts
- Ambiguity pins: 14
- Mismatch revisions: 2

## Changes
- 2.1 — revise — ambiguity — a header made up entirely of whitespace counts as empty for `ERR_UNAUTHENTICATED` — `authz.py:65`
- 2.2 (`api_request_id` bullet) — revise — ambiguity — `req_` followed by exactly twenty upper-case letters/digits — `core.py:375-379`
- 2.2 (`api_request_timestamp` bullet) — revise — ambiguity — read from the logical clock, so responses stamped while the clock sits still repeat the value — `core.py:382-386`
- 2.3 — insert — ambiguity — a supplied-but-blank `limit`/`offset` is an `ERR_INVALID_PAGINATION`; surrounding whitespace is tolerated; an absent parameter takes its default — `validate.py:126-137`
- 2.3 — insert — ambiguity — filters are exact-match equality, evaluated *after* the pagination check; bad enum or non-`true`/`false` boolean (case-insensitive) -> `ERR_INVALID_REQUEST`; a blank identifier filter is ignored — `validate.py:150-175`, ordering per `routes_charter.py:32-35`
- 2.3 — insert — ambiguity — `created_at` ties (routine under a frozen clock) break by ascending creation order, in the default and milestone orderings alike; charter list unaffected — `helpers.py:5-15`
- 2.6 — insert — ambiguity — the clock may be set backward; instants parse with `Z` or an explicit offset (normalised to UTC) and a zone-less value is read as UTC; all rendered instants carry exactly three fractional digits — `core.py:140-159`, `routes_clock.py:15`
- 2.7 — insert — ambiguity — an unrouted path and an undeclared method both answer 404 `ERR_NOT_FOUND`, the only use of that code — `app.py:42-49`
- 2.7 — revise — mismatch — "the body must parse" replaced: an absent / non-JSON / non-object body is read as an empty object, so it surfaces this rule's missing-field failure and never an earlier rule's — `validate.py:7-16`
- 2.7 — revise — ambiguity — required fields must be present *and non-null*; "non-empty" means >=1 non-whitespace char; booleans rejected where a number is required; integer fields reject float/fractional values; undeclared body fields ignored; `successor_charter_id` added to the conditionally-required list — `validate.py:27-50`, `routes_charter.py:88-89`
- 2.11 rule 5 — insert — ambiguity — an absent or out-of-vocabulary `action` is not judged at rule 5 and falls through to rule 8 — `authz.py:125-135`
- 2.11 rule 7 — revise — mismatch — `successor_charter_id` is resolved whenever present on a charter transition, whatever `action` accompanies it (PRD had scoped it to a supersession) — `routes_charter.py:85-86`
- 3.1 — insert — ambiguity — `required_functions` stored/echoed in submitted order, not sorted — `routes_charter.py:72`
- 3.1 — insert — ambiguity — seats may be added while the charter is `DRAFT` or `ADOPTED`; only `SUPERSEDED` refuses, with `ERR_ENTITY_TERMINAL` — `routes_charter.py:149-150`
- 3.1 — insert — ambiguity — supersession increments each vacated seat's `version` and recomputes the *outgoing* charter's derived attributes to 0 / empty list; the successor row is never written — `routes_charter.py:113-118`
- 4 (`GET /disclosure/charters`) — revise — ambiguity — filterable by `status` and `superseded_by_charter_id` — `routes_charter.py:34-35`
- 5 — insert — ambiguity — `ERR_NOT_FOUND` | 404 added to the catalogue — `core.py:68`

## Notes for later passes
- Left untouched (out of partition): milestone/cycle list filters (`kind`, `status`), measures/qa/deficiency list filters, and the readiness dashboard's use of `LADDER_PRIORITY` (`core.py:72-116`) — 4 rows for those endpoints still omit their filter names.
- Universality checks I ran so my wording stays safe: every list endpoint calls `pagination()` before its filters; every instant field is rendered through `fmt_instant`/`now_iso`; every integer-typed field goes through `as_integer`/`opt_integer`; no route rejects undeclared body fields; the only `allow_empty=True` strings are `reconciliation_items[].label` and `determination_note`, neither of which the PRD calls non-empty.

## Step 9 (pass 2 of 3): PRD completeness scan — cycle/cert/calc deadlines — 2026-09-03T21:03:00.000Z

All edits applied. Verification confirms pass 1's edits are intact (spot-checked three of its distinctive insertions).

## Summary

**Output size:** 526 lines before -> 526 lines after (all edits are in-paragraph, no new lines/sections). Chars 118,271 -> 121,601 (**+3,330**).

**Counts:** 11 ambiguity-pins, 4 mismatch-revisions (15 changes over 14 edit operations).

### Changes
- **2.4 (common record properties)** — insert — ambiguity — flagged the one declared exception to "`version` increments on every mutation": the cycle's slack pair as refreshed by the readiness read — `routes_cycle.py:118-142`
- **2.11 rule 20** — insert — ambiguity — the signing-side `ERR_SOD_OFFICER_SUBCERT` shares the code but not the position; it is judged last, after rule 43's coverage test — `routes_cert.py:287-289`
- **2.11 rule 36** — revise — mismatch — the "Applies to" list omitted the `OPEN_CERTIFICATION` transition, which raises the same code for a missing `APPROVED` `PERIODIC_FILING` — `routes_cycle.py:195-201`
- **3.2 (cycle transitions)** — insert — ambiguity — `note` is a <=2000-char string, may be empty, and is validated then discarded rather than stored — `routes_cycle.py:168`
- **3.2 (cycle transitions)** — revise — mismatch — PRD said the sweep "begins ... before evaluating its own gates"; impl runs it *after* rules 12 and 13, so a transition refused with `ERR_ENTITY_TERMINAL`/`ERR_INVALID_STATE` sweeps nothing — `routes_cycle.py:170-176`
- **3.2 (readiness dashboard)** — insert — ambiguity — the read's side effects are asymmetric: swept milestones keep `BREACHED` and gain `version`, while the cycle's refreshed slack pair is written in place with no `version`/`updated_at` change — `routes_cycle.py:118-142`
- **3.2 (`blocking_error_ids`)** — insert — ambiguity — each declaration gate is evaluated independently (not stopping at the first failure); terminal and state checks are mutually exclusive so an `ABANDONED` cycle never lists both; rules 1-5 never appear — `calc.py:510-543`
- **3.3 (slack)** — revise — mismatch/ambiguity — milestone creation touches the cycle and increments its `version` even when neither figure moves; trigger reworded to transitions "that have passed their terminal and state checks" — `routes_cycle.py:320-321`
- **3.3 (breach sweep)** — revise — mismatch — trigger point corrected, plus: the sweep is not rolled back when a later gate refuses the transition — `calc.py:143-151`, `routes_cycle.py:170-217`
- **3.3 (milestone gates)** — insert — ambiguity — every milestone-existence test, and `missing_milestone_kinds`, is satisfied by a milestone of that kind in *any* status including `COMPLETE`/`BREACHED` — `calc.py:489-496`
- **3.4 (exception submission)** — insert — ambiguity — `exception_note` capped at 2000 characters — `routes_cert.py:146`
- **3.8 (officer-cert registration)** — insert — ambiguity — the immediate-eligibility decision is folded into the create, so the row is returned `ELIGIBLE` at `version` 1, not as a second mutation — `routes_cert.py:245-253`
- **3.8 (signing)** — insert — ambiguity — `attestation_text` capped at 4000 characters — `routes_cert.py:261`
- **3.8 (declaring filing-ready)** — revise — mismatch — the gate has two limbs: weight exactly 0.00 **and** `restatement_stage` neither `UNDER_EVALUATION` nor `RESTATEMENT_DECLARED` (`NONE`/`REMEDIATED` pass); PRD had named only the weight — `calc.py:504-507`, `routes_cycle.py:209`
- **4 (per-cycle milestone list row)** — insert — ambiguity — added the omitted `kind` and `status` filters (pass 1's flagged item) — `routes_cycle.py:261-262`

### Left for pass 3 (with reasons)
- **2.11 rule 30's "Applies to ... an amending filing"** — the amending filing (`routes_filing.py:93`) checks the weight *only*, never `restatement_stage`, so rule 30's "is not mid-restatement" over-claims on that endpoint. I pinned the stage limb inside 3.8's declaration paragraph instead of rewriting rule 30, to avoid editing pass 3's endpoint semantics or colliding with its edit of the same clause.
- **Free-text length caps for `change_note`, `clearance_note`, `remediation_note`, `determination_note`** (all 2000 in impl) are still unpinned; those fields live in `routes_doc.py`, `routes_filing.py` and `routes_event.py`.

One cross-check worth noting: the officer-signing gate order in impl is quorum -> open events -> scope-empty -> coverage -> SOD, which matches 2.11 (21, 28, 42, 43) with SOD last; 3.8's prose enumeration lists open events after coverage, but the ladder governs and already pins the impl order, so no edit was needed there.

## Step 9 (pass 3 of 3): PRD completeness scan — doc/event/filing/calc — 2026-09-03T21:16:00.000Z

Pass 3 complete. All edits landed in the existing `workspace/PRD_COMPLETED.md` (earlier passes' text untouched except where explicitly handed to me).

## Size

| | lines | chars |
|---|---|---|
| PRD_COMPLETED.md before pass 3 | 526 | 121,601 |
| PRD_COMPLETED.md after pass 3 | 526 | 125,733 (**+4,132**, 0 line delta) |
| PRD_FINALIZED.md (baseline) | 525 | 114,132 |
| final vs FINALIZED | **+1 line** | **+11,601 chars** |

## Counts
- ambiguity-pins: **17**
- mismatch-revisions: **4**

## Changes
- 2.11 rule 7 — insert — ambiguity — `linked_document_id` is resolved whenever the field is present, including on an `ASSESS` that never uses it — `routes_event.py:113`
- 2.11 rule 30 — revise — mismatch — re-scoped the two limbs: declaration needs weight **and** `restatement_stage`; an amending filing tests weight only and never reads the stage (pass 2's hand-off #1) — `routes_filing.py:93`, `calc.py:504-507`
- 2.12 — insert — ambiguity — a row written twice in one request (tie-out re-derivation then failure cascade) still advances `version` by exactly 1 — `core.py:357-368`, `routes_doc.py:272-274`
- 3.5 — revise — mismatch — "any other cycle state is `ERR_INVALID_STATE`" over-claimed; an `ABANDONED` cycle is refused a rule earlier with `ERR_ENTITY_TERMINAL` — `routes_doc.py:102-105`
- 3.5 — insert — ambiguity — `change_note` cap of 2000 characters (hand-off #2) — `routes_doc.py:147`
- 3.6 — insert — ambiguity — duplicate `line_label` reports `ERR_INVALID_REQUEST` but is judged last on the endpoint, after rules 16/17, not at rule 8 — `routes_doc.py:251-253`
- 3.6 — insert — ambiguity — created tie-out row returns at `version` 1 (derivation folded into the create), while the owning document is touched on every create whether or not a figure moves — `routes_doc.py:272-275`, `calc.py:286`
- 3.7 — insert — ambiguity — bridging item `label` <=200 chars and may be empty; any extra property on an item is dropped, not stored — `routes_doc.py:46-56`
- 3.7 — insert — ambiguity — `reconciliation_gap` subtracts the already-rounded `reconciliation_sum`, not the raw item total — `calc.py:328-329`
- 3.7 — revise — mismatch — PRD claimed a question's target document "must" be a `CALL_SCRIPT`; the endpoint never inspects `doc_type`, so questions attach to any class and the gate constrains that document's own approval — `routes_doc.py:430-443`, `calc.py:359-362`
- 3.7 — insert — ambiguity — `clearance_note` non-empty, <=2000 chars (hand-off #2) — `routes_doc.py:468`
- 3.8 — insert — ambiguity — `determination_note` optional, <=2000, may be empty, written straight from the request so an omitted note clears an earlier one (hand-off #2) — `routes_event.py:121,142`
- 3.8 — insert — ambiguity — `ASSESS` is unavailable from `REPORTABLE` in either direction, and `NOT_REPORTABLE` only from `UNASSESSED`; both refusals `ERR_INVALID_STATE` — `routes_event.py:131-135`
- 3.8 — insert — ambiguity — disclosure overwrites `determination_note` only when supplied — `routes_event.py:177-178`
- 3.9 — insert — ambiguity — amending filing reads the weight limb alone (legal at `UNDER_EVALUATION`/`RESTATEMENT_DECLARED`), and its named document moves `APPROVED`->`FILED` as on an original — `routes_filing.py:90-94,135`
- 3.9 — insert — ambiguity — the cycle is touched on every correction assessment, so its `version` rises even on the `IMMATERIAL` branch — `routes_filing.py:291-292`
- 3.9 — insert — ambiguity — `remediation_note` non-empty, <=2000 chars (hand-off #2) — `routes_filing.py:339`
- 3.9 — revise — mismatch — closing paragraph claimed the only axis coupling is the weight reading; now states declaration reads weight + stage, amendment weight only — `routes_filing.py:93`, `calc.py:504-507`
- 4 endpoint table — insert x3 — ambiguity — declared filters for `/documents/{id}/adjusted-measures` (`status`), `/documents/{id}/qa-items` (`topic`, `risk_tier`, `status`, and target need not be a call script) and `/corrections/{id}/control-deficiencies` (`status`, `severity`) — `routes_doc.py:325,424-426`, `routes_filing.py:174-175`

## Closing cross-pass consistency read
- Rule 30 (mine), 3.8's declaration paragraph (pass 2) and 3.9's amending-filing + closing-coupling paragraphs (mine) now state the same two-limb/one-limb split with no contradiction; pass 2's 3.8 text needed no change.
- 3.5's `ABANDONED` clarification is consistent with 2.9's target-row scoping (pass 1 untouched) and with `routes_cert.py`/`routes_cycle.py`, which also answer `ERR_ENTITY_TERMINAL` for an abandoned cycle — so no 2.9 edit was needed.
- One self-inflicted contradiction caught and reconciled during the read: my 3.7 rounding clause originally called the rounded-input case "the one place" it happens, which contradicts 3.9's deficiency scoring reading an already-rounded `materiality_pct`; reworded to name both.
- Pass 1's 2.4 "increments by exactly 1 on every mutation" and my 2.12 per-request wording agree; pass 2's readiness-dashboard version exception in 2.4/3.2 is untouched and unaffected.

## Step 9 completion — orchestrator verification — 2026-09-03T21:17:00.000Z

Aggregate over the three passes: **42 ambiguity-pins + 10 mismatch-revisions = 52 edits**. Distinct md5 confirmed for all three PRD variants (PRD.md `d4f5ba16...`, PRD_FINALIZED.md `b04cacc8...`, PRD_COMPLETED.md `60f25e0e...`) — PRD_COMPLETED.md is NOT a byte-identical copy of its source, so the scan demonstrably ran. Final sizes: PRD.md 525 L / 113,792 ch; PRD_FINALIZED.md 525 L / 114,132 ch; PRD_COMPLETED.md 526 L / 125,733 ch. Tail of PRD_COMPLETED.md ends on the final error-table row `| ERR_MILESTONE_SLACK_EXHAUSTED | 409 |` — a real section boundary, no truncation.

Pipeline complete: Steps 1-9 all done, 122/122 tests passing in all 8 sweep rounds, PRD_COMPLETED.md written.

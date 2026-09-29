# Worklog — task_2582_dependent_eligibility_verification_audit

## Step 1: Create task directory — 2026-09-03T15:11:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2582_dependent_eligibility_verification_audit` and `.../workspace` using the pre-assigned path (index fixed at 2582 by the scenario number; no auto-allocation scan performed, per orchestration instructions, to avoid collision with the other pipelines running concurrently on this host).

## Step 2: Generate Scaffold — 2026-09-03T16:49:00.000Z

All three scaffold artifacts are complete and validated in `/home/ubuntu/github/CodingPRD/tasks/task_2582_dependent_eligibility_verification_audit/`.

## Files

| File | Lines | Bytes | Top-level key |
|---|---|---|---|
| `SCAFFOLD.yaml` | 2601 | 131,899 | §1.0–§1.7 (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1766 | 120,119 | `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4392 | 291,554 | `scaffold_corner_design` |

All three `yaml.safe_load` cleanly.

## Domain surface (§1.0–§1.7)
- **Profile**: `compliance_audit` / `workflow_orchestration`; layers `ops_run_checkpoint`, `cascading_side_effects`, `dual_variant_calculation`, `optimistic_concurrency`, `scheduled_deferred_actions`; flat topology, cyclic state machines, `segregation_of_duties` role model, `immediate` consistency, `api_prefix: ""`.
- **12 entities**: AuditProgram, Employee, Dependent, DocumentationRule, AuditCase, CommunicationEvent, ProofSubmission, AmnestyRemoval, Appeal, TerminationNotice, PaidClaimLine, ClaimRecovery.
- **7 state machines** + **2 OCC rules** (`scope-run-stale-program` → ERR_STALE_PROGRAM_VERSION, `recovery-create-stale-dependent` → ERR_STALE_DEPENDENT_VERSION, both 412).
- **11 calculations**, two of them dual-variant (`savings_measurement` PROVISIONAL/AUDITED, `claims_recovery_amount` STRICT/EQUITABLE) plus the pinned-order tiered `net_recovery_demand`.
- **42 priority-ordered validations** (p1–p42), **48 errors**, **45 endpoints**, **5 roles** (ProgramAdmin, VerificationAnalyst, AppealReviewer, RecoveryAgent, Employee).
- Central deferred-action engine: one `POST /audit-programs/{id}/run-sweep` call runs S1 amnesty close → S2 escalation → S3 POE lapse → S4 finalization → S5 reconciliation → S6 election expiry, with `sweep_epoch`/`version` incrementing once per mutating call.

## §1.8 difficulty design
9 rules × 2 instances = **18 instances**: `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.

## §1.9 corner design
**82 instances across all 9 sections** — 62 with full `test_recipe`, 20 `excluded_because` stubs citing the exact §1.8 instance that already covers the corner:
entities 12, state_machines 14, calculations 14, validations 25, endpoints 5, errors 1 (8-trigger not-found sweep), rbac 4, cross-cutting complexity layers 6, consistency model 1.

## Verification
- `scaffold_lint.py` → **`VERDICT: clean lint`** (1217 calls scanned across §1.8+§1.9; all conform to §1.5, all §1.1 FKs reverse-reachable).
- All **48 error ids** appear in §1.8 ∪ §1.9 grounds; all **45 endpoints** are exercised by at least one recipe call; **100 instance names**, zero duplicates across the two design files.
- Two lint fixes applied at the end: literal `expected_program_version: "1"` / `expected_dependent_version: "1"` in the RBAC lockout instance replaced with captured `${pv}` / `${dv1}`.
- Enum/field drift caught and corrected against §1.1 in the final chunks: `FAMILY` (not `EMPLOYEE_FAMILY`), `CHILD_BIOLOGICAL` (not `CHILD`), `AGE_LIMIT_EXCEEDED` (not `AGED_OUT`), `AMNESTY_REMOVED` (not `REMOVED_AMNESTY`), `penalty_waived` (not `penalty_applied`), and the PROVISIONAL savings assertion fixed to 366000 (30500 × 12) with 91500 as the removal's `audited_savings_contribution_cents`.
- The hard constraint held: no sibling `tasks/task_*/` directory was listed, read, or grepped at any point.

## Step 3: Copy Shared Files — 2026-09-03T16:49:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T17:02:00.000Z

PRD generated and verified.

**Output:** `.../workspace/PRD.md` — **450 lines, 98,559 characters**, built via 7 chunked appends (no one-shot Write), ending cleanly at the last row of the §5 error table with no audit footer.

**Structure** (domain-derived, not copied from the example): §1 three-paragraph introduction; §2 with ten subsections (RBAC → verbatim response structure → pagination → identity/logical clock → left-to-right path resolution → OCC → monetary precision & cost schedule → validation precedence → cascade integrity & counter definitions → privacy handling); §3 with nine workflow subsections (census/policy → scope → announcement & reminders → amnesty → documentation review → deferred-action checkpoint → notices & continuation → appeals → recovery/savings/close); §4 four-column endpoint table (45 rows); §5 two-column error table (48 rows).

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 129 required, 129 present, 0 missing
- endpoints[].request_body: 60 required, 60 present, 0 missing
- endpoints[].query_params/path_params: 18 required, 18 present, 0 missing
- errors[].id: 48 required, 48 present, 0 missing
- roles[].name: 5 required, 5 present, 0 missing
- enum values: 107 required, 107 present, 0 missing
- state values: 44 required, 44 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 42 checked, 42 expressed in prose (full 1–42 precedence list in §2.8), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_program_version / expected_dependent_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 51 checked, 51 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- validations[] conditions: 42 checked, 42 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 45 endpoints checked, all expressed, 0 missing
- entities[].fields[] structured content: 129 checked, reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (STRICT/EQUITABLE, PROVISIONAL/AUDITED, GRANT/DENY/REMAND, ELECT/WAIVE, ACCEPT/REJECT/REQUEST_REDACTION, three scope types, AUDIT_ESCALATION/POE_LAPSE, ISSUED→RESCINDED/FINAL→RESCINDED), 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 911
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- raw (unbackticked) path-string leaks: 0
Status: PASS
```

**Notes for the worklog:** §2.2 verified byte-identical to `section-2.2-response-structure.md`. Two scaffold ambiguities resolved conservatively in favour of the more specific source: `monthly_cost_cents` appears in the dependent-enrollment `input` list but the entity marks it computed, so the PRD states the payload key is accepted while the stored value always comes from the relationship cost schedule; and `accepted_proof_type_count` is specified with the calculation's privacy filter (`NOT_REQUIRED`/`REDACTED`/`PURGED`) rather than the entity blurb's narrower wording. Neither difficulty/corner design file was opened.

**Orchestrator truncation check (per pipeline instruction):** `tail -c 1800` confirms PRD.md terminates on the complete final error-table row `| \`ERR_PAYMENT_EXCEEDS_DEMAND\` | 422 |` — a real section boundary, not mid-sentence. Independently counted 48 `ERR_*` rows in §5 and 45 method rows in §4, matching the scaffold's 48 errors / 45 endpoints. Grep for `harder than expert` and `scaffold` in PRD.md returns 0 hits, so the difficulty instruction did not leak. No regeneration needed.

## Step 5: Generate Unit Tests — 2026-09-03T17:51:00.000Z

Stage 2 is complete. Both output directories are at the task root; nothing was written under `workspace/` (it still holds only `INSTRUCTION.md` and `PRD.md`).

## Files written

- `test_helpers/` — 9 modules, 2136 lines: `types.py`, `api_errors.py`, `constants.py`, `test_users.py`, `api_client.py` (all 48 endpoints), `factories.py`, `assertions.py`, `fixtures.py` (Builder + 12 scenario waves), `__init__.py`.
- `test_suite/` — `conftest.py` + 18 test modules, 6500 lines, **169 test functions / 186 collected cases**.

Queue A (difficulty): `test_11` savings & recovery variants (7), `test_12` premium & fee formulas (6), `test_13` non-linear lifecycles (5), `test_14` cascade propagation (6), `test_15` validation precedence (5), `test_16` boundary precision (6), `test_17` cross-entity gating (4), `test_18` temporal overlap (6), `test_19` conservation invariants (5) — 50 tests.
Queue B (corner): `test_01` (13), `test_02` (14), `test_03` (12), `test_04` (29), `test_05` (19), `test_06` (12), `test_07` (2, parametrized to 8), `test_08` (8→15), `test_09` (10) — 119 tests.

## Coverage audit (machine-verified)

- **18/18** §1.8 difficulty instances covered, every one with **>=2** tests (min 2, max 4).
- **62/62** non-stub §1.9 corner instances covered, >=1 test each. All **20** `excluded_because:` stubs left untranslated, and none is tagged.
- Every test carries **exactly one** `Design:` line as the final docstring line; all 80 tags resolve to a real instance `name:` in the yamls; no untagged, dual-tagged, or dangling tags.
- Every quoted docstring fragment is a literal whitespace-normalised substring of `workspace/PRD.md` (0 misses).
- `python3 -m py_compile` clean on all 28 generated files; `pyflakes` clean; `pytest --collect-only` → 186 tests, no import/fixture errors. Tests were not executed (`workspace/implementation/` was never read or created).

## Instances skipped / assertions withheld

No instance was skipped in full. Six individual recipe assertions were withheld because the PRD does not uniquely derive them:

1. `non_linear_state_machine/audit_case_cycles_...on_appeal_grant` — the claim that the re-opened case "can be escalated again by a later sweep" is not derivable: sweep step two fires only while the program is `RESPONSE_WINDOW`, and after a grant the program sits in `ESCALATION`.
2. `corner_notice_finalization_recomputes_savings...` — `last_savings_variant == AUDITED` after an automatic sweep; §3.9 binds that field only to an explicit measurement request.
3. `corner_documentation_rule_uniqueness_and_grace_days_phase_coupling` — the error id for a POE rule that *omits* `grace_days` (rank 5 vs rank 33 is ambiguous); the other three sub-cases are covered.
4. `corner_program_close_is_blocked_while_an_appeal_is_still_open` — the recipe decides an appeal while the program is already `RECONCILIATION`, which rank 9 forbids; split into a refusal test plus a close-after-denial test.
5. `corner_paid_claim_lines...` — stored default of an omitted `provider_type` is unstated.
6. The appeal-denial recipe's case-status assertion (§3.8 completion condition is not determined for a single-dependent case).

## Design-index defects found (PRD won)

- **Illegal `decision_reason_code` values** (`PROOF_SUFFICIENT`, `SSN_VISIBLE`, and similar) appear in many `test_recipe` blocks; the PRD permits only `VERIFIED_MATCH`, `ILLEGIBLE`, `EXPIRED_DOCUMENT`, `WRONG_DEPENDENT`, `INSUFFICIENT_PROOF`. All decisions route through `Builder.accept_proof`/`reject_proof`/`request_redaction`.
- **`provider_type: "OUTPATIENT"`** on two paid-claim setups; the declared set is `MEDICAL/DENTAL/VISION/PHARMACY`. Replaced with `MEDICAL` (subtotals unaffected).
- **Undeclared list filters** (`dependent_id` on `/claim-recoveries`, `dependent_id` on `/termination-notices`): reverse lookups were proven with PRD-enumerated filters (`termination_notice_id`, `status`, `recovery_variant`) plus client-side filtering.
- All pinned money/counter figures were re-derived from the PRD's own formulas and agreed with the yaml: 1559112/91500, 270000/120000, 50708 (not 50707), 490000→24500→514500, 500000→40000→540000, 25000 vs 24999, 152500/732000, 99426, 157500, priority 55/68/80, 2026-12-16.

**Orchestrator note on step ordering:** Steps 5 and 6 were launched in two successive messages rather than one, so the impl generator did not get physical isolation from `test_suite/` (which existed on disk by the time Step 6 started). Compensated by giving the Step 6 subagent an explicit absolute read-prohibition on `test_helpers/`, `test_suite/`, both design YAMLs, and all sibling tasks; the Step 6 agent reported implementing solely from INSTRUCTION.md + SCAFFOLD.yaml + PRD.md. Recording the deviation here for traceability.

## Step 6: Generate Implementation — 2026-09-03T18:20:00.000Z

The implementation is complete and verified.

## Files (all under `workspace/implementation/`)

**3,818 lines of Python across 23 files**, plus `start.sh` (10 lines, executable) and `requirements.txt` (`flask>=2.0`).

| Layer | Files (lines) |
|---|---|
| Boot | `app.py` (69), `start.sh`, `requirements.txt` |
| Kernel | `constants.py` (205), `errors.py` (125), `clock.py` (145), `db.py` (158), `response.py` (59), `auth.py` (81), `validate.py` (223) |
| Domain | `calc.py` (325), `serialize.py` (258), `derive.py` (255), `emit.py` (55), `sweep.py` (215) |
| Routes | `routes/__init__.py` (28), `clock_control.py` (26), `employees.py` (213), `programs.py` (424), `cases.py` (96), `submissions.py` (206), `amnesty.py` (90), `appeals.py` (283), `notices.py` (97), `recoveries.py` (182) |

`app.url_map` exposes exactly **45 endpoints**, matching PRD §4 one-for-one. Storage is module-level Python dicts in `db.py`; nothing is written to disk and nothing is seeded — a fresh process starts empty with the logical clock at `2026-08-01T00:00:00Z`.

## Organisation

- **Clock**: `clock.py` holds a single mutable "now"; every deadline, effective date, and `api_request_timestamp` reads it. No host wall clock anywhere.
- **Versioning/cascades**: `db.set_fields` marks a record dirty only on a real value change; `db.commit()` (called by every response helper) refreshes `updated_at` and bumps `version` exactly once per entity per request, so read-only touches never version-bump.
- **Counters**: `derive.refresh_all()` runs at the end of every mutating request and recomputes dependents → employees → cases → programs from scratch (§2.9), including `priority_score`, both savings figures, and the three money ledgers. `documentation_complete` is sticky-true so a granted appeal's exception is not recomputed away.
- **Validation precedence**: the 42 ranks are laid out linearly inside each view. Access control is a decorator (ranks 1–2), path 404s at rank 3, `auth.soft_owner_check_*` probes body FKs before body-shape validation so rank 4 outranks ranks 5/6, then state screens, then OCC, then business/temporal/fiscal rules. Two dependency-forced deviations are documented in-code (scope: params → rule-missing → empty; submission: privacy → window → rule → proof type → recency).
- **Calculations**: all ten live in `calc.py` with the rounding order pinned — 3 per-component roundings for the continuation premium, exactly one rounding for the admin fee, taken from the subtotal and applied before the waiver credit, per-line zero floor before summation for EQUITABLE.
- **Sweep**: `sweep.run(program)` ORs six idempotent steps (amnesty close, escalation, POE lapse, finalization, reconciliation, election expiry) and bumps `sweep_epoch` once per mutating call; each notice-issuing step keeps its own 1-based `batch_sequence_no`.
- **State machines**: parallel `review_status` × `privacy_status` on submissions; the cyclic paths (granted appeal ESCALATED→IN_PROGRESS, remand→resubmit REMANDED→SUBMITTED) are in `routes/appeals.py`, whose `_grant_cascade` applies the five compensating steps in PRD order.

## Verification

`python3 -m py_compile` passes on all 23 modules. Four smoke scenarios were run on ports 18582–18584 via `PORT=… bash start.sh`, each killed by PID and confirmed free with `ss` (no pattern kills used):

- Envelope shape confirmed on success, 400 (`ERR_INVALID_REQUEST`), 401, 403, and both 404 kinds (`ERR_PROGRAM_NOT_FOUND` for a resource, `ERR_NOT_FOUND` for an unknown route); list responses carry `limit/offset/total_count/has_more` in `meta`.
- Full audit wave: program → rules → employees → dependents → scope (OCC) → announce → submissions (privacy redaction refusal, stale document, redaction cure, accept/reject) → sweep escalation → notices → continuation ELECT/WAIVE → appeal (bad grounds, segregation, reviewer mismatch, remand, resubmit, grant cascade rescinding the notice and completing the case) → reconciliation → close (sensitive accepted submission purged).
- Money checks reproduce the PRD by hand: CHILD premium 27999+2180+931 = **31110**; STRICT subtotal 700000 → 8% → 56000 → net 751000; EQUITABLE same dependent 350000 (pre-announcement line excluded, offset-heavy line floored to zero) → 5% → 17500 → net 362500; supersession left the row that had already collected money alone; ledgers 1113500 / 2000 / 0; `ERR_OPEN_RECOVERIES_REMAIN` blocked the close.
- POE branch: enrollment picks the POE program and stamps `poe_deadline_at`, S3 lapse issues a `POE_LAPSE` notice with null `case_id`, de minimis and waiver-excess refusals fire as specified.

Two behaviours worth flagging as deliberate spec readings: a second amnesty attempt against a single-dependent case reports `ERR_CASE_STATE_INVALID` (rank 10) because §3.4 completes that case on the first removal — `ERR_AMNESTY_ALREADY_RECORDED` surfaces only while the case is still open, exactly as §2.8's note describes; and `priority_score` is recomputed on completed cases because §2.9 lists it as a derived field.

## Step 7: Run Tests and Iterate — 2026-09-03T18:38:00.000Z

Clean sweep achieved on iteration 2.

## Summary

**Iterations run:** 2 (each an 8-round parallel `per-test-server` sweep, 186 tests/round).

- Iteration 1: 184/186 in all 8 rounds — the same 2 tests failed deterministically in every round (no flakiness anywhere; no timeouts, no connection errors, no reaping).
- Iteration 2: **186/186 in all 8 rounds** (8 results files parsed, verified). Round duration ~347s.

**Tests deleted:** none. Neither failure was a case of PRD silence about a whole rule; both were test-artifact defects (STEP 2).

**Fixes applied to `test_helpers/`:** none — the fixtures/factories were consistent with PRD. The one factory-related failure was a miscall in the test function, not a factory bug.

**Fixes applied to `test_suite/`:**

1. `test_suite/test_01_census_household_and_program_setup.py` — `test_enrolling_a_dependent_under_an_undeclared_relationship_class_is_a_malformed_request`. The test called `f.dependent_payload("CHILD_BIOLOGICAL", relationship_type="NEPHEW")`, passing `relationship_type` both positionally and by keyword, so the test crashed with `TypeError` before ever issuing a request. Rebuilt as a valid `CHILD_BIOLOGICAL` payload whose `relationship_type` is then overridden to `NEPHEW`, preserving the test's intent (undeclared enum member → `ERR_INVALID_REQUEST`) exactly.

2. `test_suite/test_05_appeal_recovery_and_election_guards.py` — `test_a_remanded_appeal_that_was_resubmitted_once_cannot_be_remanded_again`. The test asserted `decided_at=None` on an appeal that had already been decided once (the first remand) and then resubmitted. PRD §3.8 enumerates resubmission's clearings exhaustively — "increments `round_number` by 1, clears `remand_reason`, and clears both `reviewer_user_id` and `assigned_at`" — and `decided_at` is not among them, while §3.8 also states "Every decision stamps `decided_at`". So a PRD-faithful implementation retains the remand's stamp; the `decided_at=None` assertion is not derivable from PRD (STEP 1c partial coverage). Replaced that one assertion with an unchanged-across-the-refusal check anchored on PRD §2.4 ("the request is rejected and nothing changes"), which preserves the test's real point — a refused second remand writes nothing — without asserting an uncovered null. The `ERR_APPEAL_ROUNDS_EXHAUSTED` / status / `round_number` / `remand_reason` assertions were all kept intact.

**Fixes applied to `implementation/`:** none. No implementation defect was found; both failures traced to the test layer.

**Orchestrator independent verification:** re-read all 8 `results.*.json` on disk myself (per the known failure mode where a Step 7 agent reports a clean sweep with no artifacts behind it). All 8 files present, timestamped together at 18:35, each parsing to `passed=186 / total=186 / failed=0`. The clean sweep is real. Step 8 is NOT skipped: Step 7 applied 2 `test_suite/` fixes, so the skip condition (0 deletions + 0 test fixes + 0 impl fixes) is not met.

## Step 8: Finalize PRD — 2026-09-03T18:42:00.000Z

`PRD_FINALIZED.md` is produced. One edit total.

## Line counts
- `PRD.md`: 450 lines
- `PRD_FINALIZED.md`: 450 lines
- Delta: **0 lines (0.00%)**; one line modified in place (line 317), one sentence inserted mid-paragraph.

## Changes
- **§3.8 (remand / resubmission)** — insert — added one sentence pinning that resubmission's enumerated clearings are exhaustive, and that the `decided_at` stamp left by the remand decision is retained across resubmission and overwritten only on the next decision — `implementation/routes/appeals.py:268-280` (resubmit never touches `decided_at`) and `implementation/routes/appeals.py:232` (`db.set_fields(appeal, decided_at=now)` on every decision).

## Per-edit pre-edit search log

**Edit 1 — §3.8 `decided_at` retention across resubmission**

(a) **Subject identified:** which fields of an `Appeal` are written/cleared by resubmission, and the full lifecycle of the appeal's `decided_at` field.

(b) **Impl paths enumerated (grepped/read):**
- `grep -rn "decided_at" --include=*.py` over the whole implementation → 6 hits: `serialize.py:105` and `serialize.py:132` (submission and appeal field lists), `routes/appeals.py:104` (creation → `None`), `routes/appeals.py:232` (every decision → `now`), `routes/submissions.py:99,158` (a *different* entity — proof submissions — so the wording was deliberately scoped to "of the appeal").
- `grep -rn '"appeals"'` to find every writer of the collection → only `routes/appeals.py` mutates appeals (`file_appeal`, `assign_appeal`, `decide_appeal`, `resubmit_appeal`); `routes/programs.py:388` only *reads* appeals for the `ERR_OPEN_APPEALS_REMAIN` close gate. `derive.py`, `sweep.py`, `calc.py` contain no appeal mutation, so no sweep step or counter recomputation can clear `decided_at`.
- Read `routes/appeals.py` in full: `decide_appeal` stamps `decided_at` unconditionally *before* branching on GRANT/DENY/REMAND, so all three decision branches (including a second decision after resubmission) write it; `resubmit_appeal` sets only `status`, `round_number`, `statement`, `remand_reason=None`, `reviewer_user_id=None`, `assigned_at=None`, plus optional `affidavit_reference`/`custody_order_reference` — confirming `decision_rationale` is likewise not cleared.
- Confirmed the refusal path (`round_number >= MAX_APPEAL_ROUNDS`) raises at lines 225-226 / 265-266 *before* any `db.set_fields`, so "nothing changes" on a refused second remand is already covered by existing §2.9 prose — no additional edit needed there.

(c) **Wording adjustment made:** two. First, "clears no other field **of the appeal**" rather than a bare "clears no other field", because `decided_at` also exists on `ProofSubmission` and an unqualified claim would have reached an unrelated entity. Second, "**overwritten only when the appeal is next decided**" rather than "never changes again", because `routes/appeals.py:232` does overwrite it on the post-resubmission decision; the looser phrasing covers all three decision branches. I also chose the general "clears no other field" over enumerating `decision_rationale` explicitly, keeping the claim true of the whole resubmit body without adding a field-specific assertion outside the Step 7 site.

## No edit made for Step 7 item 1
The `dependent_payload("CHILD_BIOLOGICAL", relationship_type="NEPHEW")` failure was a pure test-call defect (duplicate positional+keyword argument). The behavior it tested is already uniquely determined by PRD: §3.1 enumerates the seven `relationship_type` members and §2.8 rank 5 pins "enum values drawn from the declared member sets → `ERR_INVALID_REQUEST` (400)". Implementation matches exactly (`routes/employees.py:91` → `validate.req_enum(..., K.RELATIONSHIP_TYPES)`, and `validate.py` is headed "section 2.8 rank 5"). No PRD silence, so no patch.

## Step 9: Complete PRD — 2026-09-03T19:08:00.000Z

**Orchestrator decision (recorded per AUTONOMY):** Step 9 was run as **three sequential file-partitioned passes** over `implementation/` rather than one subagent, because a single-pass Step 9 on a 23-file / 3,818-line implementation reliably under-scans and can emit a PRD_COMPLETED.md byte-identical to its input (i.e. the scan never really ran). Partition: pass 1 = kernel/boot/serializer (app, constants, errors, clock, db, response, auth, validate, serialize); pass 2 = domain (calc, derive, emit, sweep); pass 3 = all 10 route modules. Each pass edited the same `PRD_COMPLETED.md` in place with unique-string `Edit` calls; pass 1 did the `cp` from `PRD_FINALIZED.md`, passes 2 and 3 were explicitly forbidden from re-copying it.

### Aggregate result
- Source `PRD_FINALIZED.md`: 450 lines / 98,780 chars → `PRD_COMPLETED.md`: **450 lines / 111,859 chars** (**+13,079 chars, +13.2%**; zero line delta — every edit is in-paragraph, as the method requires).
- **41 edits across 36 changed lines**: **34 ambiguity-pins, 7 mismatch-revisions**.
- Structure verified intact after the final pass: 45 endpoint rows in §4, 48 error rows in §5, 27 headings, all 42 ranks in §2.8, file terminating on the complete final error row. No truncation, and both earlier passes' pins survive in the final file (36 differing lines ≈ 12 + 11 + 18 edits).

### Pass 1 — kernel (12 ambiguity-pins, 0 mismatches)
- §2.1 — revise — empty header counts as absent (401); role names matched case-sensitively — `auth.py:14-19`
- §2.2 — revise — `api_request_id` = `req_` + exactly 20 uppercase-alphanumerics — `response.py:11-15`
- §2.2 — revise — `api_request_timestamp` read from the logical clock, so responses share it until the clock moves — `response.py:18-22`
- §2.2 — insert — resources are field-whitelisted: every inventory field always present, JSON `null` when unset, never omitted — `serialize.py:191-207`
- §2.3 — revise — `limit`/`offset` must be base-ten integers, rejected not clamped, default when absent/empty; `offset` unbounded — `validate.py:182-216`
- §2.3 — insert — records sharing a `created_at` are ordered by creation sequence — `db.py:152-157`
- §2.3 — insert — a filter supplied with an empty value is treated as absent — `validate.py:219-223`
- §2.4 — revise — `version` bumps once per mutating request regardless of field count or cascade writes; create-then-modify in one request persists at version 1 with `updated_at == created_at` — `db.py:76-133`
- §2.4 — revise — accepted instant forms (`Z`, numeric offset, zoneless, bare date); unparseable → `ERR_INVALID_REQUEST`; `current_utc` in an object envelope, 3 fractional digits — `clock.py:47-72,91-99`
- §2.8 rank 5 — insert — no type coercion in bodies; required `null` = missing vs optional `null` = omitted-and-defaulted; required strings non-blank; required dates real `YYYY-MM-DD` — `validate.py:32-146`
- §3.5 — revise — `reviewer_note` must be a string when supplied but is not a submission field and appears in no response — `serialize.py:93-107`
- §5 intro — insert — unrouted path and disallowed method both report `ERR_NOT_FOUND`, at 404 and 405 respectively — `app.py:34-44`

Checked-and-already-pinned (pass 1): all 5 roles and every enum member set; both cost schedules and `COMPONENT_ORDER`; the 1.02 load factor, 60/18/14/30-day constants, 2-round cap, 25,000-cent floor, fee tiers, score weights 40/25/20/15 with ceiling 100, pagination 10/1/100/0, clock epoch; all 48 error IDs and statuses; UUID ids never body-accepted; the nine versioned vs three append-only types; envelope shapes and the four pagination `meta` fields; the two-header rule with rank 1→2 ordering, operator-vs-employee `X-User-ID` semantics, transitive ownership at rank 4 above ranks 5/6, all 45 routes behind the decorator; the 13 serializer field inventories.

### Pass 2 — domain (10 ambiguity-pins, 1 mismatch)
- §2.9 — insert — the derived-field refresh is a whole-store sweep in fixed order (dependents → employees → cases → programs, not only entities the request named); re-deriving an unchanged value marks nothing dirty — `derive.py:242-255`, `db.py:112-121`
- §3.2 — insert — an id in `targeted_employee_ids` naming no employee raises no 404, matches nobody, falls through to `ERR_SCOPE_EMPTY` — `calc.py:94-96`
- §3.3 — insert — `AMNESTY_CONFIRMATION` / `TERMINATION_NOTICE` / `RESCISSION_NOTICE` written with `channel` `EMAIL` and `template_code` null — `emit.py:8,22,26`
- §3.5 — insert — `documentation_complete` is a latch: `accepted_proof_type_count` recounts from scratch but the flag never clears, which is why an appeal-granted dependent keeps it true with zero accepted documents — `derive.py:16-35,59-67`
- §3.6 — insert — cross-step chaining generalised: step 4 closing the last case lets step 5 reconcile in the same call; an all-complete program can pass `RESPONSE_WINDOW → ESCALATION → RECONCILIATION` in one invocation; all six steps always run off one clock reading — `sweep.py:203-215`
- §3.6 step 3 — insert — the step first re-runs the completeness test for every `PENDING_VERIFICATION` POE dependent and promotes those now passing to `VERIFIED`, exempting them from the lapse test even past deadline — `sweep.py:94-100`
- §3.6 step 3 — insert — a lapse notice gets no `CommunicationEvent`; step 3's `batch_sequence_no` is its own 1-based batch, independent of step 2's — `sweep.py:92,112-113`, `emit.py:11-13`
- §3.6 step 3 — insert — a lapse moves a program counter/savings figure only if that dependent also sits in a non-voided case's in-scope set — `derive.py:176-236`, `calc.py:143-168`
- §3.6 step 4 — revise — the sweep considers only the swept program's notices (its cases' notices plus case-less `POE_LAPSE` notices whose dependent's `poe_program_id` names it) — `sweep.py:11-24`
- §3.6 step 6 — revise — same program-scoped notice set — `sweep.py:187`
- §3.9 — insert — with no `announcement_at` on the anchoring program the `EQUITABLE` window opens at `ineligibility_onset_date`, still netting per line — `calc.py:188-192`
- §3.9 — revise — **MISMATCH** — the claim that `EQUITABLE` is "strictly smaller whenever any pre-announcement line exists" was false: onset-vs-announcement ordering is unvalidated, so an onset after the announcement opens the `EQUITABLE` window *earlier* and admits lines `STRICT` excludes — `calc.py:186-192`, `routes/recoveries.py:44`

Checked-and-already-pinned (pass 2): half-up rounding; the full priority-score formula incl. `max(1, divisor)`, single terminal rounding and ceiling-last; governing-rule POE-vs-AUDIT selection; the completeness gathering set and `>=` minimum; scope candidate selection and all pinned orderings; both savings variants incl. the `12 − month(coverage_end_date)` proration; the recovery window bounds and per-line zero floor; fee tiers with exact `<100000`/`<500000` boundaries and waiver-last; the three per-component premium roundings in MEDICAL/DENTAL/VISION order; termination effective-date computation incl. the POE branch and last-day-of-month; the notice field inventory; amnesty coverage-end; the reminder anchor and whole-day gap; the POE candidate filter and two-way-tie refusal; all program/case counters and the three ledgers; sweep step order, boundaries, escalation ordering and the single `sweep_epoch` bump.

### Pass 3 — routes, all 45 endpoints walked (12 ambiguity-pins, 6 mismatches)
- §2.8 rank 9 — revise — **MISMATCH** — "across all program, case, submission, amnesty, and appeal write endpoints" was a false universal; only six operations consult program phase (scope, announce, close, submission create, submission decision, amnesty removal) — `routes/appeals.py:56`, `cases.py:56`, `submissions.py:186`, `programs.py:294`
- §2.8 rank 32 — revise — **MISMATCH** — added dependent enrollment with an explicit `poe_program_id` as a third trigger — `routes/employees.py:110`
- §2.8 rank 34 — revise — **MISMATCH** — the scope run evaluates parameter shape *ahead* of rank 32's documentation-rule screen — `routes/programs.py:191-203` vs `:213`
- §2.5 — insert — per-endpoint order of two-reference body resolution (submission/appeal resolve `case_id` first; amnesty and recovery resolve `dependent_id` first) — `submissions.py:44/47`, `appeals.py:50/53`, `amnesty.py:38/41`, `recoveries.py:57/60`
- §2.3 — revise — **MISMATCH** — three supported filters were missing from the enumeration: `case_id`/`dependent_id` on appeals, `dependent_id`/`case_id` on notices, `dependent_id` on recoveries — `appeals.py:120`, `notices.py:40`, `recoveries.py:127`
- §3.1 — insert — `monthly_cost_cents` is range-validated even though never persisted — `employees.py:95`
- §3.1 — revise — explicit `poe_program_id` path: 404 on the id, missing POE rule → `ERR_DOCUMENTATION_RULE_MISSING`, and none of `poe_verification_enabled`/`plan_year`/`status` is consulted — `employees.py:105-112`
- §3.1 — revise — an omitted `grace_days` on a POE rule is `ERR_DOCUMENTATION_RULE_CONFLICT` (409), not 400; only a supplied out-of-range value is rank-5 — `programs.py:126,136-139`
- §3.2 — revise — empty `targeted_employee_ids` is a rank-34 scope-class violation, not rank 5; an empty array counts as "supplied"; JSON `null` counts as absent — `programs.py:195-203`
- §3.2 — insert — **MISMATCH** — "only `ENROLLED` are ever eligible" made re-scope impossible; pinned the projected census (returning `PENDING_VERIFICATION` dependents of still-`SELECTED` cases count as enrolled) and that a refused re-scope voids nothing — `programs.py:205-222`
- §3.5 — revise — `redaction_applied` stored false when omitted — `submissions.py:41`
- §3.5 — insert — `decision_reason_code` written only when supplied; an earlier decision's reason survives a later one that omits it — `submissions.py:167-168`
- §3.8 — revise — the appeal window anchors on the most recently issued non-rescinded notice (ties to the later-written row); no live notice → `ERR_APPEAL_WINDOW_CLOSED` — `appeals.py:71-78`
- §3.8 — insert — `decision_rationale` written only when supplied — `appeals.py:247-249`
- §3.8 — revise — **MISMATCH** — a denial completes the case only from `ESCALATED`; a `NON_RESPONSIVE` case is not completed — `appeals.py:256-258`
- §3.9 — insert — paid-claim recording has no phase or coverage-status gate; omitted `provider_type` stored null — `employees.py:172-196`
- §3.9 — insert — the notice need not belong to the named dependent; the two references are screened independently — `recoveries.py:57-72`
- §3.9 — insert — the `EQUITABLE`-anchoring program is resolved from the notice (its case's program, else the dependent's `poe_program_id`) — `recoveries.py:28-38`
- §3.9 — revise — `amount_cents` is an integer >= 0; `received_date` is required, validated, then discarded — no payment record persisted — `recoveries.py:167-168`

Checked-and-already-pinned (pass 3): the clock endpoint's role set and object envelope; every 201/200 split; `work_email` uniqueness as `ERR_INVALID_REQUEST`; the POE selector's four conditions, two sort keys, ambiguity refusal and empty-pool-is-not-an-error; program and rule defaults and uniqueness triples; scope OCC 412 and DRAFT/SCOPED gating with all pinned orderings; announcement gates, the touching-boundary overlap check and the three stamped dates; sweep 200 with epoch/version only on mutation; the close gates and four-part PURGE cascade; reminder cadence anchor, `>=` boundary and volume cap; the submission gate chain and all three decision divergences; redaction upload leaving `review_status` untouched; amnesty's four gates and full cascade; appeal filing/assign/remand/resubmit gates and the five-step grant cascade incl. `refund_due_cents = recovered_cents`; election gates with WAIVE leaving premium 0 and both dates null; recovery's three ordered gates, supersede rule, `recovery_revision` bump and demand ordering; all 45 §4 rows and all 48 §5 rows re-verified against the code.

### Final state verification (orchestrator)
- `workspace/PRD_COMPLETED.md` written, 450 lines / 111,859 chars, ends at the complete final §5 error row.
- No file under `implementation/`, `test_suite/`, or `test_helpers/` has been modified since the 18:35 clean sweep (`find -newermt` returned empty), so the verified 8/8 × 186/186 result still describes the shipped artifact. Steps 8 and 9 touched only PRD documents.
- **Pipeline complete through Step 9.**

# Worklog — task_2486_trade_publication_circulation_audit

## Step 1: Create task directory — 2026-09-02T23:55:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2486_trade_publication_circulation_audit` and its `workspace/` subdirectory. Index was pre-assigned (2486) by the orchestrating pipeline; no scan of `./tasks/` was performed, per instruction (concurrent pipelines on this host).

## Step 2: Generate Scaffold — 2026-09-03T01:47:00.000Z

Note (orchestrator): the first Step 2 subagent attempt died with "response exceeded the 64000 output token maximum" after trying to emit the whole scaffold in one tool call, and wrote no files. Relaunched with an explicit chunked-write protocol (Write for the first section, then `cat >> file <<'CHUNK_EOF'` appends, <=600 lines per call). Second attempt succeeded.

Subagent summary (verbatim):

All three artifacts are complete and lint-clean.

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2486_trade_publication_circulation_audit/`)
- `SCAFFOLD.yaml` — 2584 lines; top-level keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles. Contains **neither** design key.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1717 lines, single key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 2618 lines, single key `scaffold_corner_design`.

**§1.0–§1.7 counts**: 12 entities · 8 state machines · 2 §1.2.1 OCC rules · 9 calculations · 44 ordered validations (priorities 1–81) · 50 endpoints (18 GET, 31 business POST, 1 `POST /_clock/set_current_utc`) · 44 errors · 5 roles (4 opaque + `AdvertiserContact` entity_backed on AdvertiserContract). Profile: `expert_plus`, layers cascading_side_effects / derived_field_reconciliation / optimistic_concurrency / rate_threshold_triggers, topology flat, shape cyclic, role_model segregation_of_duties, consistency immediate.

**§1.8**: all 9 rule_ids × 2 instances = 18, each pair carrying a differentiation clause.

**§1.9**: all 9 guide sections, 72 instances (48 full `test_recipe`s + 24 `excluded_because` stubs) — entities 11/0, state_machines 6/5, calculations 4/4, validations 12/8, endpoints 3/1, errors 3/0, rbac 5/1, cross_cutting_complexity_layers 3/5, consistency_model 1/0. 52 distinct claim_types, all drawn from `references/claim-extraction-guide.md`. Verified programmatically: no duplicate instance name across the union of both design files, and every stub's `difficulty_instance` resolves to a real §1.8 instance.

**Verification**
- `python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_2486_trade_publication_circulation_audit` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (50 endpoints, 12 entities, 18 §1.8 + 48 §1.9 instances, 578 calls scanned).
- All three files `yaml.safe_load` cleanly; top-level key split confirmed as above.

**Notable adjudications**
- Two lint fixes this session: `$.data.controlled_copies` / `$.data.paid_copies` → the actual declared field names `controlled_copies_on_file` / `paid_copies_on_file` in the consistency_model recipe.
- PyYAML flow-context traps: all `$.data[N].field` captures and every bracketed `grounds:` element are quoted (unquoted plain scalars cannot contain `[`/`]`/`?` inside `{}`/`[]`).
- Publication OCC bump path: only `POST /circulation/statements` is declared to increment `Publication.version`, so the stale-version corner replays the version consumed by a successful create rather than relying on a subscriber write.
- Errors coverage closed with a single sweep instance exercising the 8 remaining scoped 404 codes, plus `ERR_DIGITAL_SOURCE_UNCERTIFIED` and a headerless `ERR_UNAUTHENTICATED` test proving auth (priority 1) beats the existence ladder.
- Segregation of duties tested on both axes with role held constant: preparer `mgr-01` refused / `mgr-02` accepted on certify, and raising auditor `aud-01` refused / `aud-02` accepted on accept-resolution.
- Hard constraint honored: no sibling task directory was listed, read, or grepped; the scaffold derives solely from the scenario plus the skill's own SKILL.md, references and lint source.

## Step 3: Copy Shared Files — 2026-09-03T01:47:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T02:00:00.000Z

Orchestrator truncation check (per the known doc-generator failure mode): `workspace/PRD.md` is 432 lines and ends at the final row of the §5 Error Code Catalogue table — a real section boundary with a complete row, not mid-sentence. Programmatic cross-check against SCAFFOLD.yaml: all 50 endpoint paths and all 44 error codes appear in the PRD (0 missing). No regeneration needed. Also confirmed the doc generator got only SCAFFOLD.yaml; neither design index was passed, and the "harder than expert level" difficulty line was NOT forwarded.

Subagent summary (verbatim):

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2486_trade_publication_circulation_audit/workspace/PRD.md` — **433 lines**, built in 8 incremental writes, ends cleanly at the §5 error table.

**Outline** (5 `##` sections, in order): §1 Introduction · §2 Global Specifications (2.1 Identity/RBAC, 2.2 Response Structure [verbatim], 2.3 Pagination, 2.4 Identity/Timestamps/Version, 2.5 Logical Clock, 2.6 Nested Addressing, 2.7 Stale-Version/OCC, 2.8 Precision, 2.9 Audit Posture, 2.10 Copies Ledger, 2.11 Make-Good Conservation, 2.12 Rejection Precedence) · §3 Business Logic (3.1 Publication+policy, 3.2 Recipient file/evidence, 3.3 Requests & review cycle, 3.4 Scoring/verification/renewal/reinstatement, 3.5 Hygiene sweeps, 3.6 Digital audience, 3.7 Statement breakdown & certification, 3.8 Engagement/sampling/findings, 3.9 Guarantees/make-goods/restatement cascade) · §4 Endpoint table (4 cols) · §5 Error table (2 cols).

**Contract 1 — Field-Name Coverage: PASS.** 156 unique identifiers (136 `entities[].fields[].name`, 78 body params, 19 query params after dedup) — all present as exact backticked tokens, 0 missing.

**Contract 2 — Rule Coverage: PASS.** 8 state machines / all transitions with preconditions+side-effects (incl. both Subscriber dimensions, the two crossing points, all 3 supersede paths, 5 auto-advance/branch transitions); 2 concurrency rules (write_endpoint + occ_field + error_id + 412 all named); 9 calculations fully reconstructible (scoring 5-step, closed-form controlled allowance with the 900→300/1200 check, breakdown + both bases, dedup reach 48000/12500/15.00→58625, tiered make-good with pinned rounding order and the 400733×12=4808796 check, reconciliation with the 1200/1176→2.00 boundary, posture ladder, both ledgers with conserved quantities); 44 validations with priority ordering rendered as the §2.12 ladder and every `applies_to` scope enumerated; 78 state/enum values present verbatim.

**Contract 3 — §3 Path Purity: PASS.** 840 backtick tokens scanned in §3; 0 starting with `/`, 0 bare HTTP methods, 0 method+path. Also verified: 0 fuzzy words, 0 pseudocode operators anywhere; §2.2 matches the canonical source byte-for-byte.

**Zero-Silence judgement calls (4 scaffold self-conflicts / gaps):**
1. `statement_type` — entity says "derived from `restates_statement_id`", endpoint + recompute say "derived from `basis`". Chose **basis-driven** (2 sources agree, and only that reading survives a basis switch on recompute).
2. `SourceDocument` — `common_fields: true` but endpoint side-effect says "no version field". Chose **common_fields: true** (§1.1 is authoritative); noted it has no general update op and that purge bumps `version`. `HygieneRun` (`common_fields: false`) is stated as `id`+`created_at` only.
3. Statement period-overlap candidate set — state machine omits `DRAFT`, validation 61 includes it. Chose **validation 61's set** (includes `DRAFT`).
4. Findings self-acceptance (`X-User-ID != raised_by_user_id`) has no error_id in the scaffold. Assigned **`ERR_SEGREGATION_OF_DUTIES` / 409** — the only segregation code in the catalogue. Similarly, future `captured_at` / `signed_at` and `newsletter_unique_opens > newsletter_sends` have no dedicated code; routed to `ERR_INVALID_REQUEST` per priority 21.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced; no sibling task directory was read.

## Step 6: Generate Implementation — 2026-09-03T02:35:00.000Z

Orchestrator note: Steps 5 and 6 were launched in back-to-back messages rather than one message, so `test_suite/` may have existed by the time the impl generator started. Physical isolation was therefore replaced with an explicit absolute prohibition in the Step 6 prompt against reading/listing/globbing/grepping `test_helpers/` or `test_suite/`; the subagent reports the prohibition held (one `ls` of the task root showed directory names only). Both agents still ran concurrently in wall-clock terms.

Subagent summary (verbatim):

Implementation complete, booted, and smoke-verified.

**Modules** (`workspace/implementation/`, 2860 lines total, `compileall` clean, no TODO/pass/NotImplementedError):
`store.py` 201 (in-memory dicts + logical clock + Decimal/date helpers), `errors.py` 84 (44 domain error ids → HTTP), `envelope.py` 80 (§2.2 envelope, pagination), `auth.py` 69 (5 roles), `validation.py` 252 (two-phase shape→enum parse), `calc.py` 373 (9 calculations, posture ladder, ledgers), `lookups.py` 52, `app.py` 66, `routes_publications.py` 192, `routes_subscribers.py` 203, `routes_requests.py` 397, `routes_statements.py` 276, `routes_audit.py` 365, `routes_commercial.py` 216, `routes_system.py` 25, plus `requirements.txt` and `start.sh` (reads `$PORT`, binds 0.0.0.0, foreground `exec python3 app.py`).

**Endpoint coverage:** 50/50 SCAFFOLD paths registered in `app.url_map` (only extra is Flask's `/static`). No missing routes.

**Boot/smoke:** booted on scratch ports 47317 and 51843 via `bash start.sh`; store empty on fresh boot (no seeding), clock defaults to 2026-08-01T00:00:00Z. Verified 201 create / 200 read / 404 / 401 unauthenticated / 403 unauthorized / 400 shape / 422 enum, and end-to-end: rules → subscribers → docs → request → review/info-loop(limit)/resubmit/verify/reject → OCC 412 both flavours → statement breakdown (600/300/300 incl., 200 excess, total 1200 = cap 25.00% exactly; digital dedup 58,625 from the PRD's worked example) → SoD → certify → period-overlap (drafts included, adjacency allowed) → settle (shortfall 60/1260 = 4.76%, tier 0.50, 24¢/insertion, 240¢) → offer/accept/waive with ledger conservation → engagement (14-day buffer: 13 days rejected, 14 accepted) → sampling auto-advance + duplicate/limit → finding respond/reject/respond/accept + SoD → clean report → condemning report 5-hop cascade (FROZEN, contracts SUSPENDED, obligations VOID) → restatement certify 3-hop unwind → both hygiene sweeps → grace-window truncation of the predecessor's `effective_to`. Both scratch servers killed.

**PRD ambiguities resolved:**
1. Terminal beats invalid-state: a terminal entity reports `ERR_ALREADY_TERMINAL` even though §2.12 ranks `ERR_INVALID_STATE`/`ERR_STATEMENT_NOT_DRAFT`/`ERR_REQUEST_NOT_UNDER_REVIEW` earlier (§3.3/§3.7 narratives are explicit).
2. Verify precondition order follows the §2.12 ladder (`WINDOW_OVERLAP` before `RULES_INCOMPLETE`/score/mandatory) over §3.4's "Finally the window…" prose; scaffold priorities 60 < 68/69/70 corroborate.
3. Threshold before mandatory-criterion (§3.4 pins it) despite scaffold priority 69 < 70.
4. `PURGED` before `SUBSCRIBER_MISMATCH` per §2.12 (50 < 51), against §3.3's prose order.
5. `statement_type` derived from `basis` (§3.7), overriding the scaffold field description tying it to `restates_statement_id`.
6. Publication `version` bumps on statement create, certify, verify, finding create, accept-resolution, condemning report, and hygiene runs (§2.7); not on subscriber/snapshot/contract writes.
7. Non-declared triggers: request from `PENDING_QUALIFICATION` → `ERR_INVALID_STATE`; re-purge → `ERR_INVALID_STATE`; settle on `DRAFT` → `ERR_INVALID_STATE`; duplicate sample subscriber → `ERR_SAMPLE_LIMIT_EXCEEDED`.
8. Fieldwork separation measured end-to-start, `later.start − earlier.end >= 14 days`; overlap = conflict.
9. Clock endpoint returns `data: {}` (§2.2 "2xx with no data"); percentages serialize as JSON numbers.

Isolation held: nothing under `test_helpers/` or `test_suite/` (or any sibling task) was read, listed, or grepped — one `ls` of the task root showed directory names only, no contents.

## Step 5: Generate Unit Tests — 2026-09-03T03:00:00.000Z

Subagent summary (verbatim):

Suite complete for `task_2486_trade_publication_circulation_audit`.

**Stage 1 — `test_helpers/` (9 files, 2,184 lines):** `types.py` 412, `fixtures.py` 484, `factories.py` 403, `api_client.py` 353, `assertions.py` 202, `api_errors.py` 115, `constants.py` 107, `test_users.py` 57, `__init__.py` 51.

**Stage 2 — `test_suite/` (19 files, 5,938 lines, 83 tests):** conftest 23; queue B `test_01`–`test_09` (454/199/278/836/403/377/248/282/77 lines → 10/3/5/12/6/4/3/3/1 tests); queue A `test_10`–`test_18` (290/234/365/341/254/286/338/277/376 lines → 4 tests each).

**Coverage:** queue A 36 tests over all 18 non-stub instances (exactly 2 each, >=2 required). Queue B 47 tests over 47 of 48 non-stub instances; the 24 `excluded_because:` stubs were not translated.

**Skipped instance (1):** `Corner/entities/create_subscriber_missing_copies_rejected` — the design asserts a missing `copies` is rejected, but PRD §3.2 states `copies` "defaults to 1", so the PRD does not derive the asserted outcome. Gap left as a gap.

**PRD-first corrections to the design recipes (translated differently, not weakened):**
- `resource_temporal_overlap/qualification_window…`: design asserts the second `verify` re-scores to 70. PRD §3.3/§3.4 recompute `computed_score` only on *entry into review*, so the test asserts the stored 100 carries into the grace-window verification.
- `transitive_cascade/hygiene_sweep…` and `cross_entity_state_dependency/certify_blocked…`: after the restatement unfreezes the publication, PRD §2.9 ("*any* change of posture … marks every DRAFT statement stale") means the previously blocked draft is stale, so I assert `breakdown_stale is True` rather than the design's "may now be certified".
- Dropped the design's claim that `paid_amount_cents` survives a reclassification out of `PAID` (not uniquely derivable); kept the class/delivery-axis and version assertions.
- All figures hand-checked against PRD worked examples (4,808,796 vs 4,808,790; 300/25.00% cap; 58,625 vs 60,500; 76,900 at 7.69%/tier 1.00; 4.9950%→5.00 rounding).

**Verification numbers:** `compileall` clean on both dirs; `pyflakes` clean (no undefined names); 83/83 tests carry exactly one trailing `Design:` line, every tag resolves to a real non-stub instance, zero unknown/stub/dual tags; `pytest --collect-only -q` → **83 tests collected, 0 errors**. No tests were run against a server; `workspace/implementation/` and all sibling task dirs were never read.

## Step 7: Run Tests and Iterate — 2026-09-03T03:20:00.000Z

Orchestrator verification (independent of the subagent's claim, per the known "clean sweep with no artifacts" failure mode): 8 `results.$i.json` files exist in `workspace/implementation/`, each ~24 KB, all written 2026-09-03T03:13, and each parses to `{'passed': 83, 'failed': 0, 'total': 83, 'errors': 0, 'skipped': 0}`. `workspace/sweep.log` ends with `83 passed in 159.51s` and contains zero `Terminated` and zero `FAILED` lines — confirming the sweep ran under `setsid` and no round was reaped. Step 8 is NOT skipped (Step 7 applied 2 implementation fixes and 6 test_suite fixes).

Subagent summary (verbatim):

All 8 rounds pass. Final report:

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each). Sweep 1: 74/83 in all 8 rounds, 9 deterministic failures (union == intersection, so no load-induced flakiness at all). Sweep 2 after fixes: 83/83 in all 8 rounds.

**Tests deleted:** none. Every failure traced to either a PRD-verbatim rule the implementation had missed, or a test artifact that mis-translated PRD. No assertion failed the STEP 1a coverage check or the STEP 1b unique-derivability check.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes_subscribers.py`, `create_subscriber()` — added `touch(pub)` after the ledger recompute. Enrolment mutates the publication's copy counters, hygiene ratio and posture, so PRD §2.4 ("`version` … increases by exactly 1 on every mutation of that resource" / "Where an operation mutates several resources at once, each mutated resource's own `version` advances") requires the publication's version to advance. Without it §2.7's stated purpose — the version check being "the only thing standing between a client and a statement computed over a population it never saw" — was defeated for the most common population change.
- `workspace/implementation/routes_subscribers.py`, `reclassify_subscriber()` — same `touch(pub)`, for the same §2.4 reason (reclassification moves copies between the publication's class buckets).

**Fixes applied to `test_suite/`** (no `test_helpers/` change was needed — the shared factories were self-consistent; the bugs were all at local call sites):
- `test_03_rbac.py::test_accept_finding_resolution_by_raising_auditor_rejected` — raised its finding against a `SCHEDULED` engagement. PRD §3.8: "Raising a finding requires the statement to be in `UNDER_AUDIT` and the engagement to be in `FIELDWORK` or `RECONCILIATION`." Added the first of the two sampled records so the engagement enters `FIELDWORK` first; imported `sample_verification_payload`.
- `test_04_validations.py::test_issue_report_with_immaterial_variance_and_live_finding_rejected` — read `report_issued_at` off the statement. Both SCAFFOLD and the test suite's own `test_helpers/types.py` declare `report_issued_at` on `AuditEngagement`, not `CirculationStatement`; the assertions now read it from the engagement (via the statement's engagement listing, which is the only engagement discovery channel per §4).
- `test_06_calculations.py` (two call sites, in `test_breakdown_counts_only_qualified_recipients_inside_the_period` and `test_reconciliation_discrepancy_exactly_at_materiality_forces_restatement`) — the local `three_dimension_policy` helper narrows `allowed_values` to `ENGINEERING_MGMT`/`MANUFACTURING`, but the requests used the global factory's default attestations (`PLANT_ENGINEER`/`MFG-311`), scoring 25 + 10 channel bonus = 35 and correctly tripping `ERR_QUALIFICATION_SCORE_BELOW_THRESHOLD` (PRD §3.4 exact, case-sensitive membership). Added matching `attested_*` overrides.
- `test_08_cross_cutting.py::test_stale_subscriber_version_on_request_create_rejected` — asserted `qualification_status == "PENDING_QUALIFICATION"` on a recipient for which no request had yet been opened. PRD §3.2: a newly enrolled recipient's `qualification_status` is `UNQUALIFIED`, and a bounce "does nothing else — neither `delivery_status` nor `qualification_status` moves". Corrected to `UNQUALIFIED`.
- `test_13_transitive_cascade.py` and `test_14_priority_pair_validation_conflict.py` — asserted `statement["certified_at"] is None`. PRD names no `certified_at`; certification "stamps `filed_at` with the current logical clock and `certified_by_user_id`". Corrected the field name to `filed_at`.
- `test_17_resource_temporal_overlap.py::test_a_draft_neighbour_is_already_in_the_candidate_set` — internally contradictory: it correctly asserted that a `DRAFT` neighbour blocks certification, then expected that same blocked neighbour's counterpart to certify while the overlapping `DRAFT` was still standing. PRD's §3.7 candidate set includes `DRAFT` and the intersection test is symmetric, so neither of two overlapping drafts can be certified. Restructured: the symmetric double-refusal is now asserted on the first publication, and the `FILED`-neighbour refusal plus the exact-adjacency permission moved to a second publication with no lingering overlapping draft. Both PRD rules are still exercised, and one extra assertion (the symmetric refusal) was gained.

**Notable non-findings:** the implementation was already correct on the two things the failures superficially pointed at — it does *not* apply the period-overlap test at statement creation (§2.7: "Nothing about statement creation is blocked by a state precondition"), and it does enforce the §3.8 engagement-state precondition on raising a finding. Both were test bugs.

**Final sweep numbers:** rounds 1–8 all `83/83` passed, 0 failed, 0 errors, 0 skipped (~159 s per round, 8 concurrent). Sweep log contains no `FAIL` lines and no `Terminated`.

## Step 8: Finalize PRD — 2026-09-03T03:30:00.000Z

Subagent summary (verbatim):

PRD_FINALIZED.md is written. Five inline edits, no new sections.

**Size:** PRD.md 432 lines / 13,946 words / 103,284 B → PRD_FINALIZED.md 432 lines (0.0% line delta) / 14,121 words (+1.25%) / 104,373 B (+1.07%).

**Changes**
- §3.2 (enrolment) — insert — enrolment also advances the *publication's* `version` by 1 (PRD previously listed only ledger/posture/draft-staleness) — `routes_subscribers.py:68`
- §3.2 (reclassification) — insert — reclassification also advances the publication's `version` by 1 — `routes_subscribers.py:127`
- §2.7 — revise — the illustrative list of operations that can invalidate `expected_publication_version` widened (enrolment/reclassification/earlier statement create) and de-exclusivised, so the two §3.2 inserts don't read as contradicting it — `routes_subscribers.py:68,127`, `routes_statements.py:98`
- §3.8 (engagement creation) — insert — engagement is created with `report_issued_at` null — `routes_audit.py:87`
- §3.9 (issue report) — revise — `report_issued_at` is a field of the **engagement**, not the statement; the engagement is the resource the issue-report call returns on both branches — `routes_audit.py:183,190,210`

**Per-edit pre-edit search log**
1. §3.2 enrolment. (a) Subject: publication `version` advancing on recipient-file mutations. (b) Enumerated `grep -n touch` across all 8 route/calc modules; read `routes_subscribers.py` in full (create/reclassify/undeliverable-event/source-doc create/purge), `routes_requests.py:300-397` (reject, hygiene run), `routes_statements.py:60-210` (create, recompute, certify), `routes_audit.py:60-265` (engagement create, finding create, issue report), `calc.py:120-190` (`recompute_publication`, `mark_drafts_stale`, `derive_posture`). Confirmed `touch(pub)` fires on enrolment, reclassify, hygiene run, verify, statement create, certify, finding raise, accept-resolution, issue-report — and *not* on undeliverable-event, source-doc attach, purge, or request reject. (c) Wording made conditional on the counters having moved and confined to the enrolment paragraph, so the neighbouring "records a bounce and does nothing else" paragraph and the purge/attach paths stay true; no exhaustive/exclusive claim made.
2. §3.2 reclassification. (a) Same subject. (b) Same enumeration reused, plus `routes_subscribers.py:121-128` where `touch(pub)` sits inside `if pub is not None`. (c) Phrased as "the publication's class buckets moved too", matching `recompute_copies_ledger`; no claim about the grand total changing.
3. §2.7. (a) Same subject, viewed from the stale-version guard. (b) Re-checked every `touch(pub)` callsite above against the sentence's list, including `routes_statements.py:98` (statement create advances pub version) and `routes_audit.py:197,264`. (c) Replaced the closed three-item list with an explicitly open formulation ("any of the operations that advance the publication's version, as each of them is described in §3") so that reject-request/undeliverable-event — which do *not* advance it — are not implicated and no future path is excluded.
4. §3.8 engagement creation. (a) Subject: engagement initial field values, specifically `report_issued_at`. (b) `grep -n report_issued_at` over all modules → only `routes_audit.py:87` (init None) and `:183` (write); read the full engagement `base_record` literal at `routes_audit.py:76-90`; confirmed one and only one engagement creation path, and that `_sampled` is stripped by `store.serialize`. (c) None.
5. §3.9 issue report. (a) Subject: where `report_issued_at` lives and what issue-report returns. (b) Same grep confirmed the statement record (`routes_statements.py:70-95`) has no `report_issued_at`; read both return paths `routes_audit.py:190` (clearing) and `:210` (condemning) — both `return ok(serialize(engagement))`; checked `store.serialize`; cross-checked that `discrepancy_copies`/`discrepancy_pct` genuinely are written on the statement (`:181-182`). (c) Kept "Both values are written onto the statement" verbatim, and scoped the return-value claim to this call only rather than generalising §2.2's default.

Non-edits (PRD already uniquely determines the behaviour; the Step 7 items were test-local bugs): the §3.8 engagement-state precondition on raising a finding, the §3.4 case-sensitive attestation membership, the §3.2 `UNQUALIFIED`-on-enrolment / bounce-moves-nothing rules, `filed_at` as the certification stamp, and the §3.7 overlap candidate set — verified `OVERLAP_CANDIDATE_STATUSES` in `routes_statements.py:15-16` matches the PRD's six statuses and the predicate at `:188-189` is strict/half-open, permitting exact adjacency.

## Step 9: Complete PRD — 2026-09-03T03:52:00.000Z

Orchestrator verification: `workspace/PRD_COMPLETED.md` is 433 lines (source `PRD_FINALIZED.md` 432; the single added line is one bullet inside the existing §2.2 list). Heading sets are byte-identical between source and output (27 each, `diff` of the heading lines is empty), and the file still ends at the final `| ERR_NO_SHORTFALL_TO_SETTLE | 409 |` row of the §5 error table — no section dropped, no truncation. Also confirmed `implementation/` was not touched by Steps 8 or 9: newest module mtime is 03:09 (`routes_subscribers.py`, Step 7's fix), which predates the clean 8-round sweep at 03:13, so the verified 83/83 result still describes the shipped implementation.

PIPELINE COMPLETE. Final artifacts: SCAFFOLD.yaml + both design indices, worklog.md, test_helpers/ (9 files), test_suite/ (19 files, 83 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (15 modules + start.sh + requirements.txt + results.1..8.json)}.

Subagent summary (verbatim):

**PRD_COMPLETED.md written** — `/home/ubuntu/github/CodingPRD/tasks/task_2486_trade_publication_circulation_audit/workspace/PRD_COMPLETED.md`

Source 432 lines / 104373 chars / 27 headings → output 433 lines / 119837 chars / 27 headings (+1 line, +15464 chars). Heading list byte-identical; file still ends at `| ERR_NO_SHORTFALL_TO_SETTLE | 409 |`. No new sections; the single added line is one bullet inside the existing §2.2 list. 38 targeted edits: 34 ambiguity-pins, 4 mismatch-revisions.

Modules walked (all 15): store ✓ errors ✓ envelope ✓ auth ✓ validation ✓ calc ✓ lookups ✓ app ✓ routes_system ✓ routes_publications ✓ routes_subscribers ✓ routes_requests ✓ routes_statements ✓ routes_audit ✓ routes_commercial ✓. §4's 50 rows verified 1:1 against the 50 registered routes.

- §2.1 — insert — ambiguity — blank/whitespace `X-User-ID` fails auth before role membership; AdvertiserContact's user id *is* its contract id — auth.py:31-44, routes_commercial.py:25-31
- §2.2 — insert — ambiguity — new bullet: unset fields serialize as `null`, Decimals as JSON numbers (`5.00`→`5.0`), key order insignificant — store.py:serialize
- §2.2 — insert — ambiguity — non-paginated 2xx array (settle-guarantees only) carries `response_type` array with no pagination meta — envelope.py:ok_array
- §2.3 — insert — ambiguity — empty-string limit/offset = absent; non-integer or out-of-range → ERR_INVALID_REQUEST 400; undeclared query params ignored — envelope.py:_int_param
- §2.3 — insert — ambiguity — `has_more` = offset + returned < total_count; offset past end → empty data, true total_count — envelope.py:paginate
- §2.3 — insert — ambiguity — `created_at` ties broken by creation sequence; hygiene-run newest-first is that order reversed; bad enum filter → ERR_INVALID_ENUM_VALUE 422; unknown id filter narrows to zero — store.py:collection_sorted, validation.py:filter_enum
- §2.4 — insert — ambiguity — timestamps always 3 fractional digits + `Z`; inbound accepts `Z`/offset/naive-as-UTC; month arithmetic clamps day-of-month — store.py:fmt_dt/parse_dt/add_months
- §2.5 — insert — ambiguity — `to_iso8601` max 64 chars; clock may move backwards; response is empty object — routes_system.py:15-27
- §2.6 — insert — ambiguity — percentages 2dp ROUND_HALF_UP, 0.00 when denominator 0; copy quotients truncate toward zero — store.py:ratio_pct/floor_div_decimal
- §2.7 — insert — ambiguity — absent body = `{}`; non-object body → ERR_INVALID_REQUEST; unknown fields ignored; explicit `null` on an optional field takes the default — validation.py:body/parse
- §2.7 — insert — ambiguity — strict types, no coercion: bools/floats/numeric strings rejected for integer fields; every string field's max length stated — validation.py:_check_int/_check_str
- §2.7 — insert — ambiguity — shape errors for *all* fields precede any enum-membership check (two-phase parse) — validation.py:parse
- §2.8 — insert — ambiguity — non-string identifiers hit the same not-found error as missing ones — lookups.py:_get
- §2.8 — insert — ambiguity — unrouted path → ERR_NOT_FOUND 404, wrong verb → ERR_METHOD_NOT_ALLOWED 405, unexpected fault → ERR_INTERNAL 500; trailing slashes tolerated — app.py:strict_slashes/errorhandlers
- §2.9 — insert — ambiguity — `expected_*_version` compared before state checks; absent means no check; version advances only on real mutation — routes_publications.py, store.py:touch
- §2.12 — revise — mismatch — step 8's internals: ERR_REQUEST_NOT_UNDER_REVIEW first, then ERR_ALREADY_TERMINAL on the acted-on entity, then ERR_STATEMENT_NOT_DRAFT/ERR_INVALID_STATE on related entities — routes_requests.py:212, routes_statements.py, routes_commercial.py:123-136
- §3.1 — insert — ambiguity — rule-set edits/threshold changes mark DRAFT statements stale and bump the publication version; posture recomputed on every mutation — calc.py:recompute_publication/mark_drafts_stale
- §3.1 — insert — ambiguity — controlled-copy allowance closed form `core * cap / (100 - cap)` truncated; cap of 100 impossible by field range — calc.py:controlled_allowance
- §3.2 — insert — ambiguity — enrolment defaults (`copies` 1, `paid_amount_cents` 0, UNQUALIFIED/DELIVERABLE, score 0) and the publication `touch` that follows — routes_subscribers.py:44-68
- §3.2 — revise — mismatch — `paid_amount_cents` is stored on reclassify whenever supplied, for any target class, and omission keeps the stored amount for the PAID check — routes_subscribers.py:110-118
- §3.2 — insert — ambiguity — undeliverable event takes an optional `reason_code` (<=200), always increments, never auto-suppresses — routes_subscribers.py:136-142
- §3.2 — insert — ambiguity — `captured_at` in the future of the logical clock → ERR_INVALID_REQUEST; retention from `captured_at` + publication's retention months — routes_subscribers.py:154-174
- §3.2 — insert — ambiguity — purging an already-purged document → ERR_INVALID_STATE, *ahead of* the retention gate — routes_subscribers.py:200-204
- §3.3 — revise — mismatch — evidence-check order is state refusals, then purged-document, then subscriber mismatch — routes_requests.py:56-70
- §3.3 — insert — ambiguity — creating a request for a recipient already PENDING_QUALIFICATION → ERR_INVALID_STATE — routes_requests.py:56
- §3.3 — insert — ambiguity — information requests capped at 2 (ERR_INFO_REQUEST_LIMIT on the third); each attachment <= its stated length — calc.py:INFO_REQUEST_LIMIT, routes_requests.py
- §3.4 — revise — mismatch — the fieldwork-window collision check runs *before* rules-complete, threshold and mandatory-rule checks, not last — routes_requests.py:243 vs 248-262
- §3.4 — insert — ambiguity — `computed_score` is persisted even when verification is refused — routes_requests.py:254
- §3.4 — insert — ambiguity — scoring constants pinned: 12-month freshness window, 5/month decay capped at 30, +10 DM / +5 WEB·EMAIL, ceiling 100, threshold 70 — calc.py:qualification_score
- §3.5 — insert — ambiguity — hygiene runs list newest-first; run records are immutable once written — calc.py, routes_publications.py
- §3.6 — insert — ambiguity — statement breakdown recomputed from live recipients at draft time; DRAFT statements go stale on any upstream mutation — calc.py:compute_statement_breakdown
- §3.7 — insert — ambiguity — 14-day fieldwork buffer measured as elapsed time between windows with exactly 14 days accepted; REPORT_ISSUED engagements ignored; overlap counts as zero gap — routes_audit.py:58-74
- §3.7 — insert — ambiguity — sampling: a repeat recipient and a RECONCILIATION engagement share ERR_SAMPLE_LIMIT_EXCEEDED; SCHEDULED auto-advances to FIELDWORK; RECONCILIATION at sample_size — routes_audit.py:130-146
- §3.8 — insert — ambiguity — findings: SoD blocks the raising auditor from accepting; accept-resolution returns the statement to UNDER_AUDIT only when no live finding remains; `response_count` increments per response — routes_audit.py:344-360
- §3.9 — insert — ambiguity — settle-guarantees on a DRAFT statement → ERR_INVALID_STATE, and success returns HTTP 201 with the array of obligations created — routes_statements.py:228,276
- §3.9 — insert — ambiguity — shortfall make-good rounds per insertion first, then `bonus = credit // gross_rate`; credit conservation across pool/committed/waived/available — calc.py:shortfall_makegood/recompute_contract_ledger
- §3.9 — insert — ambiguity — condemning-report cascade order (statement → publication → contracts by creation order → PENDING/OFFERED obligations VOID with closed_reason) — routes_audit.py:193-209
- §3.9 — insert — ambiguity — snapshot adjudication: re-adjudication → ERR_ALREADY_TERMINAL; REJECT accepted from any source; validator id recorded — routes_commercial.py:206-215

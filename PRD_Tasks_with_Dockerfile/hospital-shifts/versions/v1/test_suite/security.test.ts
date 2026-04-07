import {
  apiClient,
  buildUserHeaders,
  handleApiResponse,
  validateErrorEnvelope,
  createTreatmentPlanPayload,
  createWardRotationPayload,
  createProcedurePayload,
  createMedicalResourcePayload,
  createInfectionRiskPairingPayload,
  TreatmentPlan,
  WardRotation,
  Procedure,
  MedicalResource,
  InfectionRiskPairing,
  ApiErrorId,
  createAndActivatePlan,
  createAssignmentPayload,
  Assignment,
} from '../../../test-helpers';

const chargeNurseHeaders = buildUserHeaders('cn-sec-1', 'ChargeNurse');
const physicianHeaders = buildUserHeaders('physician-sec-1', 'AttendingPhysician');

const SQL_INJECTION_PAYLOADS = [
  "'; DROP TABLE treatment_plans; --",
  "' OR '1'='1",
  "admin'--",
  "' UNION SELECT * FROM users--",
  "normal'; UPDATE treatment_plans SET total_budget=999999 WHERE id='...",
];

function containsSQLError(response: any): boolean {
  const responseStr = JSON.stringify(response);
  const sqlErrorPatterns = [
    /SQL syntax/i,
    /SQLSTATE/i,
    /mysql_/i,
    /pg_/i,
    /ORA-/i,
    /ODBC/i,
    /syntax error/i,
    /database error/i,
    /column .* does not exist/i,
    /table .* does not exist/i,
    /sqlite/i,
    /constraint/i,
  ];

  return sqlErrorPatterns.some(pattern => pattern.test(responseStr));
}

describe('Security: SQL Injection Prevention', () => {
  describe('String Fields', () => {
    it('should safely handle SQL injection in all user-controlled string fields', async () => {
      const plan = await createAndActivatePlan();

      for (const payload of SQL_INJECTION_PAYLOADS.slice(0, 3)) {
        const planPayload = createTreatmentPlanPayload({ plan_name: payload });
        const createRes = await apiClient.createTreatmentPlan(planPayload, chargeNurseHeaders);

        expect([201, 400]).toContain(createRes.status);
        expect(createRes.status).not.toBe(500);
        expect(containsSQLError(createRes.data)).toBe(false);

        if (createRes.status === 201) {
          const createdPlan = handleApiResponse<TreatmentPlan>(createRes, 201);
          const getRes = await apiClient.getTreatmentPlan(createdPlan.id, chargeNurseHeaders);
          const retrieved = handleApiResponse<TreatmentPlan>(getRes, 200);
          expect(retrieved.plan_name).toBe(payload);
        } else {
          validateErrorEnvelope(createRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
        }
      }

      const sqlPayload = "Rotation'; DELETE FROM ward_rotations WHERE '1'='1'; --";
      const rotationPayload = createWardRotationPayload({ name: sqlPayload });
      const rotationRes = await apiClient.createWardRotation(plan.id, rotationPayload, physicianHeaders);

      expect([201, 400]).toContain(rotationRes.status);
      expect(rotationRes.status).not.toBe(500);
      expect(containsSQLError(rotationRes.data)).toBe(false);

      if (rotationRes.status === 201) {
        const rotation = handleApiResponse<WardRotation>(rotationRes, 201);
        const getRes = await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders);
        const retrieved = handleApiResponse<WardRotation>(getRes, 200);
        expect(retrieved.name).toBe(sqlPayload);
      } else {
        validateErrorEnvelope(rotationRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
      }

      const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders)
        .then(res => handleApiResponse<WardRotation>(res, 201));

      const procPayload = "SURGERY'; UPDATE assignments SET status='COMPLETED'--";
      const procedureRes = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ procedure_type: procPayload }), physicianHeaders);

      expect([201, 400]).toContain(procedureRes.status);
      expect(procedureRes.status).not.toBe(500);
      expect(containsSQLError(procedureRes.data)).toBe(false);

      if (procedureRes.status === 201) {
        const procedure = handleApiResponse<Procedure>(procedureRes, 201);
        expect(procedure.procedure_type).toBe(procPayload);
      } else {
        validateErrorEnvelope(procedureRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
      }

      const resourceRes = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({
        resource_name: "Resource'; DROP TABLE medical_resources; --",
        resource_model: "Model' OR '1'='1"
      }), physicianHeaders);

      expect([201, 400]).toContain(resourceRes.status);
      expect(resourceRes.status).not.toBe(500);
      expect(containsSQLError(resourceRes.data)).toBe(false);

      if (resourceRes.status === 201) {
        const resource = handleApiResponse<MedicalResource>(resourceRes, 201);
        expect(resource.resource_name).toBe("Resource'; DROP TABLE medical_resources; --");
        expect(resource.resource_model).toBe("Model' OR '1'='1");
      } else {
        validateErrorEnvelope(resourceRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
      }

      const res1 = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload(), physicianHeaders)
        .then(res => handleApiResponse<MedicalResource>(res, 201));
      const res2 = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload(), physicianHeaders)
        .then(res => handleApiResponse<MedicalResource>(res, 201));

      const pairingPayload = createInfectionRiskPairingPayload(res1.id, res2.id, { reason: "Test'; DELETE FROM assignments WHERE '1'='1'; --" });
      const pairingRes = await apiClient.createInfectionRiskPairing(plan.id, pairingPayload, chargeNurseHeaders);

      expect([201, 400]).toContain(pairingRes.status);
      expect(pairingRes.status).not.toBe(500);
      expect(containsSQLError(pairingRes.data)).toBe(false);

      if (pairingRes.status === 201) {
        const pairing = handleApiResponse<InfectionRiskPairing>(pairingRes, 201);
        expect(pairing.reason).toBe("Test'; DELETE FROM assignments WHERE '1'='1'; --");
      } else {
        validateErrorEnvelope(pairingRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
      }
    });
  });

  describe('UUID Path Parameters', () => {
    it('should reject SQL injection and malformed input in all UUID path parameters', async () => {
      const plan = await createAndActivatePlan();

      const malformedPayloads = [
        "not-a-uuid",
        "' OR '1'='1",
        "00000000-0000-0000-0000-000000000000'; DROP TABLE treatment_plans; --",
        "../../../etc/passwd",
        "uuid'; UNION SELECT * FROM users--",
      ];

      for (const malformed of malformedPayloads) {
        const res = await apiClient.getTreatmentPlan(malformed, chargeNurseHeaders);

        expect(res.status).toBeGreaterThanOrEqual(400);
        expect(res.status).toBeLessThan(600);

        if (res.data && typeof res.data === 'object') {
          expect(res.data.response_type).not.toBe('object');
          expect(res.data.response_type).not.toBe('array');
        }

        expect(containsSQLError(res.data)).toBe(false);
      }

      const malformedRotation = "rotation-id'; DELETE FROM ward_rotations; --";
      const rotationRes = await apiClient.getWardRotation(plan.id, malformedRotation, chargeNurseHeaders);
      expect([400, 404]).toContain(rotationRes.status);
      expect(containsSQLError(rotationRes.data)).toBe(false);
      if (rotationRes.status === 404) {
        validateErrorEnvelope(rotationRes, { expectedErrorId: ApiErrorId.ERR_ROTATION_NOT_FOUND });
      } else {
        validateErrorEnvelope(rotationRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
      }

      const traversalRes = await apiClient.getWardRotation(plan.id, '../../../etc/passwd', chargeNurseHeaders);
      expect([400, 404]).toContain(traversalRes.status);
      expect(containsSQLError(traversalRes.data)).toBe(false);

      const resourceRes = await apiClient.getMedicalResource(plan.id, "resource-id' OR '1'='1", chargeNurseHeaders);
      expect([400, 404]).toContain(resourceRes.status);
      expect(containsSQLError(resourceRes.data)).toBe(false);
      if (resourceRes.status === 404) {
        validateErrorEnvelope(resourceRes, { expectedErrorId: ApiErrorId.ERR_RESOURCE_NOT_FOUND });
      } else {
        validateErrorEnvelope(resourceRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
      }

      const assignmentRes = await apiClient.getAssignment(plan.id, "assignment-id'; DROP TABLE assignments; --", chargeNurseHeaders);
      expect([400, 404]).toContain(assignmentRes.status);
      expect(containsSQLError(assignmentRes.data)).toBe(false);
      if (assignmentRes.status === 404) {
        validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });
      } else {
        validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
      }

      const pairingRes = await apiClient.getInfectionRiskPairing(plan.id, "pairing-id' UNION SELECT * FROM infection_risk_pairings--", chargeNurseHeaders);
      expect([400, 404]).toContain(pairingRes.status);
      expect(containsSQLError(pairingRes.data)).toBe(false);
      if (pairingRes.status === 404) {
        validateErrorEnvelope(pairingRes, { expectedErrorId: ApiErrorId.ERR_PAIRING_NOT_FOUND });
      } else {
        validateErrorEnvelope(pairingRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
      }
    });

    it('should reject valid UUID with SQL injection suffix', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders)
        .then(res => handleApiResponse<WardRotation>(res, 201));

      const injectionSuffixes = [
        "' OR 1=1--",
        "'; SELECT pg_sleep(5)--",
        "' OR '1'='1'--",
      ];

      for (const suffix of injectionSuffixes) {
        const planRes = await apiClient.getTreatmentPlan(plan.id + suffix, chargeNurseHeaders);
        expect([400, 404]).toContain(planRes.status);
        expect(containsSQLError(planRes.data)).toBe(false);

        const rotationRes = await apiClient.getWardRotation(plan.id, rotation.id + suffix, chargeNurseHeaders);
        expect([400, 404]).toContain(rotationRes.status);
        expect(containsSQLError(rotationRes.data)).toBe(false);
      }
    });

    it('should reject SQL injection on all mutation endpoint path parameters', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders)
        .then(res => handleApiResponse<WardRotation>(res, 201));
      const procedure = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload(), physicianHeaders)
        .then(res => handleApiResponse<Procedure>(res, 201));
      const resource = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload(), physicianHeaders)
        .then(res => handleApiResponse<MedicalResource>(res, 201));
      const assignment = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource.id), physicianHeaders)
        .then(res => handleApiResponse<Assignment>(res, 201));

      const inj = "' OR 1=1--";

      const activateRes = await apiClient.activateTreatmentPlan(plan.id + inj, chargeNurseHeaders);
      expect([400, 404]).toContain(activateRes.status);
      expect(containsSQLError(activateRes.data)).toBe(false);

      const reviewRes = await apiClient.initiateFinalReview(plan.id + inj, chargeNurseHeaders);
      expect([400, 404]).toContain(reviewRes.status);
      expect(containsSQLError(reviewRes.data)).toBe(false);

      const updateRotationRes = await apiClient.updateWardRotationStatus(plan.id, rotation.id + inj, { status: 'READY_FOR_ASSIGNMENT' }, chargeNurseHeaders);
      expect([400, 404]).toContain(updateRotationRes.status);
      expect(containsSQLError(updateRotationRes.data)).toBe(false);

      const cancelProcRes = await apiClient.cancelProcedure(plan.id, rotation.id, procedure.id + inj, physicianHeaders);
      expect([400, 404]).toContain(cancelProcRes.status);
      expect(containsSQLError(cancelProcRes.data)).toBe(false);

      const protocolApproveRes = await apiClient.protocolApproveAssignment(plan.id, assignment.id + inj, chargeNurseHeaders);
      expect([400, 404]).toContain(protocolApproveRes.status);
      expect(containsSQLError(protocolApproveRes.data)).toBe(false);

      const rejectRes = await apiClient.rejectAssignment(plan.id, assignment.id + inj, chargeNurseHeaders);
      expect([400, 404]).toContain(rejectRes.status);
      expect(containsSQLError(rejectRes.data)).toBe(false);

      const cancelRes = await apiClient.cancelAssignment(plan.id, assignment.id + inj, chargeNurseHeaders);
      expect([400, 404]).toContain(cancelRes.status);
      expect(containsSQLError(cancelRes.data)).toBe(false);

      const certRes = await apiClient.addMedicalResourceCertification(plan.id, resource.id + inj, { name: 'BSL-3_CERTIFIED', applied_date: '2025-01-01' }, physicianHeaders);
      expect([400, 404]).toContain(certRes.status);
      expect(containsSQLError(certRes.data)).toBe(false);
    });
  });

  describe('Encoding & Special Character Attacks', () => {
    it('should handle unicode, multi-byte, control characters, and encoded injection patterns', async () => {
      const encodingPayloads = [
        "Plan\u0027 OR \u00271\u0027=\u00271",
        "Test\u003B DROP TABLE plans\u003B --",
        "名前'; DROP TABLE treatment_plans; --",
        "🔥'; UPDATE plans SET budget=0; --",
        "Plan\x00Name'; DROP TABLE treatment_plans; --",
        "Name\r\nInjection",
        "/* /* nested */ comment */ ' OR 1=1--",
        "%2527%2520OR%25201%253D1--",
        "Test%00' OR 1=1--",
      ];

      for (const payload of encodingPayloads) {
        const planPayload = createTreatmentPlanPayload({ plan_name: payload });
        const res = await apiClient.createTreatmentPlan(planPayload, chargeNurseHeaders);

        expect([201, 400]).toContain(res.status);
        expect(res.status).not.toBe(500);
        expect(containsSQLError(res.data)).toBe(false);

        if (res.status === 201) {
          const plan = handleApiResponse<TreatmentPlan>(res, 201);
          const retrieved = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
            .then(res => handleApiResponse<TreatmentPlan>(res, 200));
          expect(retrieved.plan_name).toBe(payload);
        } else {
          validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
        }
      }
    });
  });
});

describe('Security: Second-Order SQL Injection', () => {
  it('should not execute SQL stored in resource names during subsequent queries', async () => {
    const plan = await createAndActivatePlan();

    const payload = createMedicalResourcePayload({
      resource_name: "Resource'; UPDATE treatment_plans SET total_budget=999999; --"
    });
    const createRes = await apiClient.createMedicalResource(plan.id, payload, physicianHeaders);
    const resource = handleApiResponse<MedicalResource>(createRes, 201);

    await apiClient.getMedicalResources(plan.id, undefined, physicianHeaders);

    const planCheck = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const planData = handleApiResponse<TreatmentPlan>(planCheck, 200);

    expect(planData.total_budget).not.toBe(999999);
    expect(planData.total_budget).toBeGreaterThan(0);
  });

  it('should prevent multi-statement and chained SQL execution via stored data', async () => {
    const plan = await createAndActivatePlan();

    const maliciousResourceName = "Resource'; UPDATE treatment_plans SET total_budget=999999; --";
    const resourcePayload = createMedicalResourcePayload({ resource_name: maliciousResourceName });
    const resourceRes = await apiClient.createMedicalResource(plan.id, resourcePayload, physicianHeaders);
    const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

    const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders)
      .then(res => handleApiResponse<WardRotation>(res, 201));
    const procedure = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload(), physicianHeaders)
      .then(res => handleApiResponse<Procedure>(res, 201));

    const assignment1 = await apiClient.createAssignment(
      plan.id,
      createAssignmentPayload(procedure.id, resource.id),
      physicianHeaders
    ).then(res => handleApiResponse<Assignment>(res, 201));

    const resource2 = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload(), physicianHeaders)
      .then(res => handleApiResponse<MedicalResource>(res, 201));

    const pairingPayload = createInfectionRiskPairingPayload(
      resource.id,
      resource2.id,
      { reason: "Test'; DELETE FROM assignments WHERE '1'='1'; --" }
    );

    await apiClient.createInfectionRiskPairing(plan.id, pairingPayload, chargeNurseHeaders);

    await apiClient.getMedicalResources(plan.id, undefined, physicianHeaders);
    await apiClient.getAssignments(plan.id, undefined, chargeNurseHeaders);
    await apiClient.getInfectionRiskPairings(plan.id, undefined, chargeNurseHeaders);

    const planCheck = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const planData = handleApiResponse<TreatmentPlan>(planCheck, 200);

    expect(planData.total_budget).not.toBe(999999);
    expect(planData.total_budget).toBeGreaterThan(0);

    expect(planData.status).toBe('ACTIVE');

    const finalAssignments = await apiClient.getAssignments(plan.id, undefined, chargeNurseHeaders);
    const assignments = handleApiResponse<Assignment[]>(finalAssignments, 200, { expectPaginated: true });
    const foundAssignment = assignments.find(a => a.id === assignment1.id);
    expect(foundAssignment).toBeDefined();
  });
});

describe('Security: Mass Assignment Protection', () => {
  it('should reject or ignore all system-managed fields across all resources', async () => {
    const plan = await createAndActivatePlan();

    const planPayload = {
      ...createTreatmentPlanPayload(),
      id: 'custom-id-12345',
      created_at: '2020-01-01T00:00:00.000Z',
      updated_at: '2020-01-01T00:00:00.000Z',
      version: 999,
    } as any;

    const planRes = await apiClient.createTreatmentPlan(planPayload, chargeNurseHeaders);

    if (planRes.status === 400) {
      validateErrorEnvelope(planRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    } else {
      const createdPlan = handleApiResponse<TreatmentPlan>(planRes, 201);
      expect(createdPlan.id).not.toBe('custom-id-12345');
      expect(createdPlan.version).toBe(1);
      expect(createdPlan.created_at).not.toBe('2020-01-01T00:00:00.000Z');
    }

    const rotationPayload = {
      ...createWardRotationPayload(),
      id: 'custom-rotation-id',
      version: 777,
      created_at: '2019-01-01T00:00:00.000Z',
    } as any;

    const rotationRes = await apiClient.createWardRotation(plan.id, rotationPayload, physicianHeaders);

    if (rotationRes.status === 400) {
      validateErrorEnvelope(rotationRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
      return;
    }

    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);
    expect(rotation.id).not.toBe('custom-rotation-id');
    expect(rotation.version).toBe(1);

    const procedurePayload = {
      ...createProcedurePayload(),
      id: 'custom-proc-id',
      version: 555,
    } as any;

    const procedureRes = await apiClient.createProcedure(plan.id, rotation.id, procedurePayload, physicianHeaders);

    if (procedureRes.status === 400) {
      validateErrorEnvelope(procedureRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    } else {
      const procedure = handleApiResponse<Procedure>(procedureRes, 201);
      expect(procedure.id).not.toBe('custom-proc-id');
      expect(procedure.version).toBe(1);
    }
  });

  it('should reject or ignore all readonly derived fields', async () => {
    const plan = await createAndActivatePlan();

    const planPayload = {
      ...createTreatmentPlanPayload(),
      cost_balance: 999999,
      patient_safety_score: -100,
    } as any;

    const planRes = await apiClient.createTreatmentPlan(planPayload, chargeNurseHeaders);

    if (planRes.status === 400) {
      validateErrorEnvelope(planRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    } else {
      const createdPlan = handleApiResponse<TreatmentPlan>(planRes, 201);
      expect(createdPlan.cost_balance).toBe(createdPlan.total_budget);
      expect(createdPlan.patient_safety_score).toBe(0);
    }

    const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders)
      .then(res => handleApiResponse<WardRotation>(res, 201));

    const procedurePayload = {
      ...createProcedurePayload({ start_minute: 100, end_minute: 200 }),
      duration_minutes: 9999,
    } as any;

    const procedureRes = await apiClient.createProcedure(plan.id, rotation.id, procedurePayload, physicianHeaders);

    if (procedureRes.status === 400) {
      validateErrorEnvelope(procedureRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    } else {
      const procedure = handleApiResponse<Procedure>(procedureRes, 201);
      expect(procedure.duration_minutes).toBe(100);
    }
  });

  it('should reject or ignore status override attempts on all resources', async () => {
    const plan = await createAndActivatePlan();

    const planPayload = {
      ...createTreatmentPlanPayload(),
      status: 'COMPLETED',
    } as any;

    const planRes = await apiClient.createTreatmentPlan(planPayload, chargeNurseHeaders);

    if (planRes.status === 400) {
      validateErrorEnvelope(planRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    } else {
      const createdPlan = handleApiResponse<TreatmentPlan>(planRes, 201);
      expect(createdPlan.status).toBe('PLANNING');
    }

    const rotationPayload = {
      ...createWardRotationPayload(),
      status: 'COMPLETED',
    } as any;

    const rotationRes = await apiClient.createWardRotation(plan.id, rotationPayload, physicianHeaders);

    if (rotationRes.status === 400) {
      validateErrorEnvelope(rotationRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
      return;
    }

    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);
    expect(rotation.status).toBe('PLANNING');

    const procedure = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload(), physicianHeaders)
      .then(res => handleApiResponse<Procedure>(res, 201));
    const resource = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload(), physicianHeaders)
      .then(res => handleApiResponse<MedicalResource>(res, 201));

    const assignmentPayload = {
      ...createAssignmentPayload(procedure.id, resource.id),
      status: 'COMPLETED',
      final_cost: 999.99,
    } as any;

    const assignmentRes = await apiClient.createAssignment(plan.id, assignmentPayload, physicianHeaders);

    if (assignmentRes.status === 400) {
      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    } else {
      const assignment = handleApiResponse<Assignment>(assignmentRes, 201);
      expect(assignment.status).toBe('PENDING_SCHEDULE');
      expect(assignment.final_cost == null).toBe(true);
    }
  });

  it('should reject or ignore unknown and malicious fields', async () => {
    const payload = {
      ...createTreatmentPlanPayload(),
      admin_flag: true,
      is_superuser: "'; DROP TABLE users; --",
      sql_injection: "' OR '1'='1",
      __proto__: { polluted: true },
      constructor: { prototype: { isAdmin: true } },
      hidden_field: 'should_not_appear',
    } as any;

    const res = await apiClient.createTreatmentPlan(payload, chargeNurseHeaders);

    if (res.status === 400) {
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    } else {
      const plan = handleApiResponse<TreatmentPlan>(res, 201);

      expect((plan as any).admin_flag).toBeUndefined();
      expect((plan as any).is_superuser).toBeUndefined();
      expect((plan as any).sql_injection).toBeUndefined();
      expect((plan as any).hidden_field).toBeUndefined();
    }
  });
});

describe('Security: Data Integrity & Storage', () => {
  it('should store and retrieve all special characters, whitespace, and case exactly as provided', async () => {
    const testPayloads = [
      "<script>alert('XSS')</script>",
      "<img src=x onerror=alert(1)>",
      "<iframe src='evil.com'></iframe>",
      "' OR '1'='1",
      "'; DROP TABLE plans; --",
      "Name with 'single quotes'",
      'Name with "double quotes"',
      "Name with <angle brackets>",
      "Name with & ampersand",
      "Name with \\ backslash",
      'Plan with {curly braces}',
      'Plan with [square brackets]',
      'Name with\ttabs',
      'Name with\nnewlines',
      'Name with    multiple spaces',
      '  Leading and trailing spaces  ',
      'ALL UPPERCASE',
      'all lowercase',
      'MiXeD CaSe',
      "Complex: <tag> 'quoted' & special; --SQL comment",
    ];

    for (const testPayload of testPayloads) {
      const payload = createTreatmentPlanPayload({ plan_name: testPayload });
      const createRes = await apiClient.createTreatmentPlan(payload, chargeNurseHeaders);

      expect([201, 400]).toContain(createRes.status);
      expect(createRes.status).not.toBe(500);
      expect(containsSQLError(createRes.data)).toBe(false);

      if (createRes.status === 201) {
        const plan = handleApiResponse<TreatmentPlan>(createRes, 201);
        expect(plan.plan_name).toBe(testPayload);

        const getRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
        const retrieved = handleApiResponse<TreatmentPlan>(getRes, 200);
        expect(retrieved.plan_name).toBe(testPayload);
      } else {
        validateErrorEnvelope(createRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
      }
    }
  });

  it('should maintain data integrity across multiple resource types', async () => {
    const plan = await createAndActivatePlan();

    const htmlRotationName = "<b>Bold Rotation</b>";
    const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload({ name: htmlRotationName }), physicianHeaders)
      .then(res => handleApiResponse<WardRotation>(res, 201));

    const sqlProcedureType = "Type'; DELETE FROM procedures; --";
    const procedure = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ procedure_type: sqlProcedureType }), physicianHeaders)
      .then(res => handleApiResponse<Procedure>(res, 201));

    expect(rotation.name).toBe(htmlRotationName);
    expect(procedure.procedure_type).toBe(sqlProcedureType);

    const retrievedRotation = await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders)
      .then(res => handleApiResponse<WardRotation>(res, 200));
    const retrievedProcedure = await apiClient.getProcedure(plan.id, rotation.id, procedure.id, physicianHeaders)
      .then(res => handleApiResponse<Procedure>(res, 200));

    expect(retrievedRotation.name).toBe(htmlRotationName);
    expect(retrievedProcedure.procedure_type).toBe(sqlProcedureType);
  });
});

describe('Security: Pagination Parameter Hardening', () => {
  it('should safely handle SQL injection and invalid values in pagination parameters', async () => {
    const plan = await createAndActivatePlan();

    await apiClient.createWardRotation(plan.id, createWardRotationPayload({ name: 'Test 1' }), physicianHeaders);
    await apiClient.createWardRotation(plan.id, createWardRotationPayload({ name: 'Test 2' }), physicianHeaders);

    const invalidLimits = [
      -1,
      0,
      101,
      "10; DROP TABLE ward_rotations; --",
      "' OR '1'='1",
      NaN,
      Infinity,
    ];

    for (const invalidLimit of invalidLimits) {
      const res = await apiClient.getWardRotations(plan.id, { limit: invalidLimit } as any, chargeNurseHeaders);

      expect([400, 200]).toContain(res.status);
      expect(res.status).not.toBe(500);
      expect(containsSQLError(res.data)).toBe(false);

      if (res.status === 200) {
        expect(res.data.response_type).toBe('array');
        expect(res.data.meta).toBeDefined();
      } else {
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
      }
    }

    const invalidOffsets = [
      -1,
      "0' OR '1'='1",
      "10; DELETE FROM ward_rotations; --",
      NaN,
      Infinity,
    ];

    for (const invalidOffset of invalidOffsets) {
      const res = await apiClient.getWardRotations(plan.id, { offset: invalidOffset } as any, chargeNurseHeaders);

      expect([400, 200]).toContain(res.status);
      expect(res.status).not.toBe(500);
      expect(containsSQLError(res.data)).toBe(false);

      if (res.status === 400) {
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
      }
    }
  });
});

describe('Security: Header Validation Hardening', () => {
  it('should safely handle SQL injection and invalid values in authentication headers', async () => {
    const maliciousRoles = [
      "ChargeNurse'; DROP TABLE users; --",
      "AttendingPhysician' OR '1'='1",
      "HospitalAdministrator\'; DELETE FROM treatment_plans; --",
    ];

    for (const maliciousRole of maliciousRoles) {
      const headers = {
        'X-User-ID': 'user-1',
        'X-User-Role': maliciousRole,
      };

      const res = await apiClient.getTreatmentPlans(headers);

      expect(res.status).toBe(400);
      expect(res.status).not.toBe(500);
      expect(containsSQLError(res.data)).toBe(false);
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });
    }

    const maliciousUserIds = [
      "user-1'; DROP TABLE treatment_plans; --",
      "admin' OR '1'='1",
      "' UNION SELECT * FROM users--",
    ];

    for (const maliciousId of maliciousUserIds) {
      const headers = {
        'X-User-ID': maliciousId,
        'X-User-Role': 'ChargeNurse',
      };

      const res = await apiClient.getTreatmentPlans(headers);

      expect(res.status).not.toBe(500);
      expect([400, 200]).toContain(res.status);
      expect(containsSQLError(res.data)).toBe(false);
    }

    const longUserId = 'A'.repeat(10000);
    const longHeaderRes = await apiClient.getTreatmentPlans({
      'X-User-ID': longUserId,
      'X-User-Role': 'ChargeNurse',
    });

    expect(longHeaderRes.status).not.toBe(500);
    expect([400, 200]).toContain(longHeaderRes.status);
    expect(containsSQLError(longHeaderRes.data)).toBe(false);
  });
});

describe('Security: Type Strictness & JSON Structure Validation', () => {
  it('should reject string values in numeric fields', async () => {
    const stringNumericPayloads = [
      { total_budget: "1000" },
      { total_budget: "1000' OR '1'='1" },
      { total_budget: "999; DROP TABLE plans; --" },
    ];

    for (const override of stringNumericPayloads) {
      const payload = { ...createTreatmentPlanPayload(), ...override } as any;
      const res = await apiClient.createTreatmentPlan(payload, chargeNurseHeaders);

      expect(res.status).toBeGreaterThanOrEqual(400);
      expect(res.status).toBeLessThan(600);

      if (res.data && typeof res.data === 'object') {
        expect(res.data.response_type).not.toBe('object');
        expect(res.data.response_type).not.toBe('array');
      }

      expect(containsSQLError(res.data)).toBe(false);
    }
  });

  it('should reject NaN and Infinity in numeric fields', async () => {
    const invalidNumericPayloads = [
      { total_budget: NaN },
      { total_budget: Infinity },
      { total_budget: -Infinity },
    ];

    for (const override of invalidNumericPayloads) {
      const payload = { ...createTreatmentPlanPayload(), ...override } as any;
      const res = await apiClient.createTreatmentPlan(payload, chargeNurseHeaders);

      expect(res.status).toBeGreaterThanOrEqual(400);
      expect(res.status).toBeLessThan(600);

      if (res.data && typeof res.data === 'object') {
        expect(res.data.response_type).not.toBe('object');
        expect(res.data.response_type).not.toBe('array');
      }

      expect(containsSQLError(res.data)).toBe(false);
    }
  });

  it('should handle numeric overflow values appropriately', async () => {
    const overflowValues = [
      Number.MAX_SAFE_INTEGER * 10,
      1e308,
      Number.MAX_VALUE * 2,
    ];

    for (const value of overflowValues) {
      const payload = createTreatmentPlanPayload({ total_budget: value });
      const res = await apiClient.createTreatmentPlan(payload, chargeNurseHeaders);

      expect(res.status).not.toBe(500);
      expect([400, 201, 413]).toContain(res.status);
      expect(containsSQLError(res.data)).toBe(false);

      if (res.status === 201) {
        const plan = handleApiResponse<TreatmentPlan>(res, 201);
        expect(typeof plan.total_budget).toBe('number');
        expect(isFinite(plan.total_budget)).toBe(true);
      } else {
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
      }
    }
  });

  it('should reject arrays in scalar string fields', async () => {
    const arrayPayloads = [
      { plan_name: ["Plan' OR '1'='1 --"], total_budget: 1000 },
      { plan_name: "Test", total_budget: [1000, 2000] },
    ];

    for (const payload of arrayPayloads) {
      const res = await apiClient.createTreatmentPlan(payload as any, chargeNurseHeaders);

      expect(res.status).toBeGreaterThanOrEqual(400);
      expect(res.status).toBeLessThan(600);

      if (res.data && typeof res.data === 'object') {
        expect(res.data.response_type).not.toBe('object');
        expect(res.data.response_type).not.toBe('array');
      }

      expect(containsSQLError(res.data)).toBe(false);
    }
  });

  it('should reject objects in scalar fields', async () => {
    const objectPayloads = [
      { plan_name: "Test", total_budget: { value: "1000 OR 1=1" } },
      { plan_name: { name: "Test' OR 1=1--" }, total_budget: 1000 },
    ];

    for (const payload of objectPayloads) {
      const res = await apiClient.createTreatmentPlan(payload as any, chargeNurseHeaders);

      expect(res.status).toBeGreaterThanOrEqual(400);
      expect(res.status).toBeLessThan(600);

      if (res.data && typeof res.data === 'object') {
        expect(res.data.response_type).not.toBe('object');
        expect(res.data.response_type).not.toBe('array');
      }

      expect(containsSQLError(res.data)).toBe(false);
    }
  });

  it('should reject SQL injection in boolean fields', async () => {
    const plan = await createAndActivatePlan();
    const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders)
      .then(res => handleApiResponse<WardRotation>(res, 201));
    const procedure = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload(), physicianHeaders)
      .then(res => handleApiResponse<Procedure>(res, 201));
    const resource = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload(), physicianHeaders)
      .then(res => handleApiResponse<MedicalResource>(res, 201));

    const sqlInBoolean = [
      "true' OR 1=1--",
      "false'; DROP TABLE assignments;--",
      "1 OR 1=1",
    ];

    for (const malicious of sqlInBoolean) {
      const res = await apiClient.createAssignment(
        plan.id,
        { ...createAssignmentPayload(procedure.id, resource.id), override_protocol_check: malicious as any },
        physicianHeaders
      );

      expect(res.status).toBeGreaterThanOrEqual(400);
      expect(res.status).toBeLessThan(600);

      if (res.data && typeof res.data === 'object') {
        expect(res.data.response_type).not.toBe('object');
        expect(res.data.response_type).not.toBe('array');
      }

      expect(containsSQLError(res.data)).toBe(false);
    }
  });

  it('should reject string values in procedure minute fields', async () => {
    const plan = await createAndActivatePlan();
    const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders)
      .then(res => handleApiResponse<WardRotation>(res, 201));

    const invalidPayload = createProcedurePayload({
      start_minute: "100" as any,
      end_minute: "200" as any,
    });

    const res = await apiClient.createProcedure(plan.id, rotation.id, invalidPayload, physicianHeaders);

    expect(res.status).toBe(400);
    expect(containsSQLError(res.data)).toBe(false);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INVALID_PROCEDURE_MINUTES });
  });
});

describe('Security: Cross-Container Access Prevention', () => {
  it('should prevent horizontal privilege escalation via path injection to access cross-plan resources', async () => {
    const planA = await createAndActivatePlan(10000, 'Plan A');
    const planB = await createAndActivatePlan(10000, 'Plan B');

    const rotationA = await apiClient.createWardRotation(planA.id, createWardRotationPayload({ name: 'Rotation A' }), physicianHeaders)
      .then(res => handleApiResponse<WardRotation>(res, 201));
    const resourceA = await apiClient.createMedicalResource(planA.id, createMedicalResourcePayload({ resource_name: 'Resource A' }), physicianHeaders)
      .then(res => handleApiResponse<MedicalResource>(res, 201));
    const procedureA = await apiClient.createProcedure(planA.id, rotationA.id, createProcedurePayload({ procedure_type: 'Procedure A' }), physicianHeaders)
      .then(res => handleApiResponse<Procedure>(res, 201));
    const assignmentA = await apiClient.createAssignment(planA.id, createAssignmentPayload(procedureA.id, resourceA.id), physicianHeaders)
      .then(res => handleApiResponse<Assignment>(res, 201));

    const injectionSuffixes = [
      "' OR 1=1--",
      "' OR planId='" + planA.id + "'--",
      "' UNION SELECT * FROM ward_rotations WHERE plan_id='" + planA.id + "'--",
    ];

    for (const suffix of injectionSuffixes) {
      const rotationRes = await apiClient.getWardRotation(planB.id + suffix, rotationA.id, chargeNurseHeaders);
      expect([400, 404]).toContain(rotationRes.status);
      expect(rotationRes.status).not.toBe(200);
      expect(containsSQLError(rotationRes.data)).toBe(false);

      const resourceRes = await apiClient.getMedicalResource(planB.id + suffix, resourceA.id, chargeNurseHeaders);
      expect([400, 404]).toContain(resourceRes.status);
      expect(resourceRes.status).not.toBe(200);
      expect(containsSQLError(resourceRes.data)).toBe(false);

      const assignmentRes = await apiClient.getAssignment(planB.id + suffix, assignmentA.id, chargeNurseHeaders);
      expect([400, 404]).toContain(assignmentRes.status);
      expect(assignmentRes.status).not.toBe(200);
      expect(containsSQLError(assignmentRes.data)).toBe(false);
    }

    const normalRotationRes = await apiClient.getWardRotation(planB.id, rotationA.id, chargeNurseHeaders);
    expect(normalRotationRes.status).toBe(404);
    validateErrorEnvelope(normalRotationRes, { expectedErrorId: ApiErrorId.ERR_ROTATION_NOT_FOUND });
  });
});

describe('Security: Body vs Path Scope Override', () => {
  it('should reject or ignore body-provided plan_id when path already scopes to a different plan', async () => {
    const planA = await createAndActivatePlan(10000, 'Plan A');
    const planB = await createAndActivatePlan(10000, 'Plan B');

    const rotationA = await apiClient.createWardRotation(planA.id, createWardRotationPayload(), physicianHeaders)
      .then(res => handleApiResponse<WardRotation>(res, 201));
    const procedureA = await apiClient.createProcedure(planA.id, rotationA.id, createProcedurePayload(), physicianHeaders)
      .then(res => handleApiResponse<Procedure>(res, 201));
    const resourceA = await apiClient.createMedicalResource(planA.id, createMedicalResourcePayload(), physicianHeaders)
      .then(res => handleApiResponse<MedicalResource>(res, 201));

    const maliciousPayload = {
      ...createAssignmentPayload(procedureA.id, resourceA.id),
      plan_id: planB.id,
    } as any;

    const res = await apiClient.createAssignment(planA.id, maliciousPayload, physicianHeaders);

    expect([201, 400]).toContain(res.status);
    expect(res.status).not.toBe(500);
    expect(containsSQLError(res.data)).toBe(false);

    if (res.status === 201) {
      const assignment = handleApiResponse<Assignment>(res, 201);
      expect(assignment.plan_id).toBe(planA.id);
      expect(assignment.plan_id).not.toBe(planB.id);

      const getViaA = await apiClient.getAssignment(planA.id, assignment.id, chargeNurseHeaders);
      expect(getViaA.status).toBe(200);

      const getViaB = await apiClient.getAssignment(planB.id, assignment.id, chargeNurseHeaders);
      expect(getViaB.status).toBe(404);
      validateErrorEnvelope(getViaB, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });
    } else {
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    }
  });
});

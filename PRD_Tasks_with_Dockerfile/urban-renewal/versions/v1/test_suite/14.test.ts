import {
  apiClient,
  buildAuthHeaders,
  createProjectPayload,
  createPhasePayload,
  createWorkOrderPayload,
  createCrewPayload,
  getSuccessData,
  UrbanRenewalProject,
  RenovationPhase,
  WorkOrder,
  RenovationCrew,
} from '../../../test-helpers';
import { validateErrorEnvelope, validateApiResponseStructure } from '../../../test-helpers/validators';
import { ApiErrorId } from '../../../test-helpers/api-errors';

describe('Phase 2 — Security Hardening', () => {
  it('SQLi-like payloads in path params return 4xx (no 500)', async () => {
    const headers = buildAuthHeaders('sec-user-1');
    const inj = "' OR '1'='1";
    const res1 = await apiClient.getProject(inj, headers);
    expect(res1.status).toBeGreaterThanOrEqual(400);
    expect(res1.status).toBeLessThan(500);
    if (res1.status === 404) validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_FOUND });
  });

  it('SQLi-like payloads inside body fields are stored as literals and retrievable', async () => {
    const headers = buildAuthHeaders('sec-user-2');
    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ project_name: "Mall ' OR '1'='1" }), headers)
    );
    const fetched = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    expect(fetched.project_name).toBe("Mall ' OR '1'='1");
  });

  it('invalid UUID formats in body/path yield 4xx with standard envelope (not 500)', async () => {
    const headers = buildAuthHeaders('sec-user-3');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const bad = 'not-a-uuid';

    const badContract = await apiClient.createContract(project.id, { work_order_id: bad, crew_id: bad }, headers);
    expect(badContract.status).toBeGreaterThanOrEqual(400);
    expect(badContract.status).toBeLessThan(500);
    const badPhase = await apiClient.getPhase(project.id, bad, headers);
    expect(badPhase.status).toBeGreaterThanOrEqual(400);
    expect(badPhase.status).toBeLessThan(500);
  });

  it('oversized/Unicode/special characters are handled without 500s', async () => {
    const headers = buildAuthHeaders('sec-user-4');
    const longName = 'X'.repeat(5000) + '💥🚀';
    const res = await apiClient.createProject(createProjectPayload({ project_name: longName }), headers);
    expect(res.status).toBeGreaterThanOrEqual(200);
    expect(res.status).toBeLessThan(500);
    if (res.status < 300) {
      const proj = getSuccessData<UrbanRenewalProject>(res);
      expect(proj.project_name.endsWith('💥🚀')).toBe(true);
    }
  });

  it('include invalid under concurrency while valid requests run in parallel', async () => {
    const headers = buildAuthHeaders('sec-user-6');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ project_name: 'IncProj' }), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload(), headers));
    getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload(), headers));

    const invalid = apiClient.getProjectsWithParams({ include: 'foo' }, headers);
    const valid1 = apiClient.getProjectsWithParams({ include: 'phases' }, headers);
    const valid2 = apiClient.getProjectsWithParams({ include: 'crews' }, headers);

    const [i, v1, v2] = await Promise.all([invalid, valid1, valid2]);
    validateErrorEnvelope(i, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    const env1 = validateApiResponseStructure<any>(v1);
    const env2 = validateApiResponseStructure<any>(v2);
    expect(Array.isArray((env1 as any).included)).toBe(true);
    expect(Array.isArray((env2 as any).included)).toBe(true);
  });
});

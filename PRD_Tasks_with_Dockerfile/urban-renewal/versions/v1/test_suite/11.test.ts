import {
  apiClient,
  buildAuthHeaders,
  createProjectPayload,
  createPhasePayload,
  createWorkOrderPayload,
  createCrewPayload,
  createContractPayload,
  getSuccessData,
  UrbanRenewalProject,
  RenovationPhase,
  WorkOrder,
  RenovationCrew,
  CrewContract,
} from '../../../test-helpers';

const expectIndicesInAscendingOrder = (indices: number[]) => {
  for (let i = 1; i < indices.length; i++) {
    expect(indices[i - 1]).toBeLessThan(indices[i]);
  }
};

const expectSortedByCreatedAtThenId = (items: Array<{ created_at: string; id: string }>) => {
  for (let i = 1; i < items.length; i++) {
    const prevTime = Date.parse(items[i - 1].created_at);
    const currTime = Date.parse(items[i].created_at);
    expect(prevTime).toBeLessThanOrEqual(currTime);
  }
};

describe('Sorting Guarantees', () => {
  it('GET /projects returns created projects in created_at order', async () => {
    const headers = buildAuthHeaders('sort-user-projects');
    const p1 = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ project_name: 'SortProjA' }), headers));
    const p2 = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ project_name: 'SortProjB' }), headers));
    const p3 = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ project_name: 'SortProjC' }), headers));

    const list = getSuccessData<UrbanRenewalProject[]>(await apiClient.getProjects(headers));
    const indices = [p1.id, p2.id, p3.id].map(id => list.findIndex(p => p.id === id));
    indices.forEach(i => expect(i).toBeGreaterThanOrEqual(0));
    expectIndicesInAscendingOrder(indices);
    const createdEntries = list.filter(p => [p1.id, p2.id, p3.id].includes(p.id));
    expectSortedByCreatedAtThenId(createdEntries);
  });

  it('GET /projects/{projId}/contracts returns contracts sorted by created_at', async () => {
    const headers = buildAuthHeaders('sort-user-contracts');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ project_name: 'SortContracts' }), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crewA = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Crew-A' }), headers));
    const crewB = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Crew-B' }), headers));

    const wo1 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ task_type: 'first' }), headers));
    const wo2 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ task_type: 'second', start_hour: 20, end_hour: 30 }), headers));

    const c1 = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(wo1.id, crewA.id), headers));
    const c2 = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(wo2.id, crewB.id), headers));

    const contracts = getSuccessData<CrewContract[]>(await apiClient.getContracts(project.id, headers));
    expect(contracts.map(c => c.id)).toEqual([c1.id, c2.id]);
    expectSortedByCreatedAtThenId(contracts);
  });

  it('GET /projects/{projId}/crews returns crews sorted by created_at', async () => {
    const headers = buildAuthHeaders('sort-user-crews');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ project_name: 'SortCrews' }), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const crew1 = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'CrewA' }), headers));
    const crew2 = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'CrewB' }), headers));

    const crews = getSuccessData<RenovationCrew[]>(await apiClient.getCrews(project.id, headers));
    expect(crews.map(c => c.id)).toEqual([crew1.id, crew2.id]);
    expectSortedByCreatedAtThenId(crews);
  });

  it('GET /projects/{projId}/phases/{phaseId}/work-orders returns work orders sorted by created_at', async () => {
    const headers = buildAuthHeaders('sort-user-workorders');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ project_name: 'SortWOProj' }), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));

    const wo1 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ task_type: 'T1' }), headers));
    const wo2 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ task_type: 'T2', start_hour: 40, end_hour: 50 }), headers));

    const workOrders = getSuccessData<WorkOrder[]>(await apiClient.getWorkOrders(project.id, phase.id, headers));
    expect(workOrders.map(w => w.id)).toEqual([wo1.id, wo2.id]);
    expectSortedByCreatedAtThenId(workOrders);
  });
});

import {
  apiClient,
  buildAuthHeaders,
  createContractPayload,
  createCrewPayload,
  createPhasePayload,
  createProjectPayload,
  createWorkOrderPayload,
  getSuccessData,
  CrewContract,
  RenovationPhase,
  UrbanRenewalProject,
  WorkOrder,
} from '../../../../test-helpers';
import { validateErrorEnvelope } from '../../../../test-helpers/validators';
import { ApiErrorId } from '../../../../test-helpers/api-errors';

describe('Concurrency — Phase Cancellation Cascade Races', () => {
  it('phase cancel vs child schedule: cancellation dominates and rewinds work order + contract', async () => {
    const user = 'phase-cascade-schedule';
    const headers = buildAuthHeaders(user);

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ project_name: 'Phase Cancel Cascade' }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload({ name: 'Cascade Phase' }), headers)
    );

    const crew = getSuccessData(
      await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Cascade Crew' }), headers)
    );

    const workOrder = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Window Fit', start_hour: 0, end_hour: 8 }),
        headers
      )
    );

    const contract = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(workOrder.id, crew.id), headers)
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contract.id, headers));

    const [phaseCancelRes, scheduleRes] = await Promise.all([
      apiClient.updatePhaseStatus(project.id, phase.id, { status: 'CANCELLED' }, headers),
      apiClient.scheduleWork(project.id, contract.id, headers),
    ]);

    expect(phaseCancelRes.status).toBe(200);

    if (scheduleRes.status >= 200 && scheduleRes.status < 300) {
      getSuccessData<CrewContract>(scheduleRes);
    } else {
      validateErrorEnvelope(scheduleRes, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_SPECIALIZATION_VERIFIED });
    }

    const finalPhase = getSuccessData<RenovationPhase>(await apiClient.getPhase(project.id, phase.id, headers));
    expect(finalPhase.status).toBe('CANCELLED');

    const finalWorkOrder = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, workOrder.id, headers)
    );
    expect(finalWorkOrder.status).toBe('CANCELLED');

    const finalContract = getSuccessData<CrewContract>(await apiClient.getContract(project.id, contract.id, headers));
    expect(finalContract.status).toBe('CANCELLED');
  });

  it('phase cancel vs contract reject: cascade applies once; terminal state is consistent', async () => {
    const user = 'phase-cascade-reject';
    const headers = buildAuthHeaders(user);

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ project_name: 'Phase Cancel Reject' }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload({ name: 'Reject Phase' }), headers)
    );

    const crew = getSuccessData(
      await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Reject Crew' }), headers)
    );

    const workOrder = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Drywall', start_hour: 100, end_hour: 120 }),
        headers
      )
    );

    const contract = getSuccessData<CrewContract>(
      await apiClient.createContract(project.id, createContractPayload(workOrder.id, crew.id), headers)
    );

    const [phaseCancelRes, rejectRes] = await Promise.all([
      apiClient.updatePhaseStatus(project.id, phase.id, { status: 'CANCELLED' }, headers),
      apiClient.rejectContract(project.id, contract.id, headers),
    ]);

    expect(phaseCancelRes.status).toBe(200);

    if (rejectRes.status >= 200 && rejectRes.status < 300) {
      getSuccessData<CrewContract>(rejectRes);
    } else {
      validateErrorEnvelope(rejectRes, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_PROPOSED });
    }

    const finalPhase = getSuccessData<RenovationPhase>(await apiClient.getPhase(project.id, phase.id, headers));
    expect(finalPhase.status).toBe('CANCELLED');

    const finalWorkOrder = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, workOrder.id, headers)
    );
    expect(finalWorkOrder.status).toBe('CANCELLED');

    const finalContract = getSuccessData<CrewContract>(await apiClient.getContract(project.id, contract.id, headers));
    expect(['CANCELLED', 'REJECTED']).toContain(finalContract.status);
  });

  it('phase cancel vs newborn proposal: cancellation either blocks creation or immediately cascades it', async () => {
    const user = 'phase-cascade-newborn';
    const headers = buildAuthHeaders(user);

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(createProjectPayload({ project_name: 'Phase Cancel Newborn' }), headers)
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(project.id, createPhasePayload({ name: 'Newborn Phase' }), headers)
    );

    const crew = getSuccessData(
      await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Newborn Crew' }), headers)
    );

    const workOrder = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Painting', start_hour: 200, end_hour: 220 }),
        headers
      )
    );

    const [phaseCancelRes, createContractRes] = await Promise.all([
      apiClient.updatePhaseStatus(project.id, phase.id, { status: 'CANCELLED' }, headers),
      apiClient.createContract(project.id, createContractPayload(workOrder.id, crew.id), headers),
    ]);

    expect(phaseCancelRes.status).toBe(200);

    if (createContractRes.status === 201) {
      const created = getSuccessData<CrewContract>(createContractRes);
      expect(created.status).toBe('PROPOSED');
    } else {
      validateErrorEnvelope(createContractRes, { expectedErrorId: ApiErrorId.ERR_WORK_ORDER_NOT_PENDING });
    }

    const finalPhase = getSuccessData<RenovationPhase>(await apiClient.getPhase(project.id, phase.id, headers));
    expect(finalPhase.status).toBe('CANCELLED');

    const finalWorkOrder = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, workOrder.id, headers)
    );
    expect(finalWorkOrder.status).toBe('CANCELLED');

    const contracts = getSuccessData<CrewContract[]>(await apiClient.getContracts(project.id, headers));
    const contractsForWO = contracts.filter(c => c.work_order_id === workOrder.id);

    expect(contractsForWO.length).toBeLessThanOrEqual(1);
    if (contractsForWO.length === 1) {
      expect(contractsForWO[0].status).toBe('CANCELLED');
    }
  });
});
